"""
Changelog:

20190206 WJV
- started this Changelog
- manually checked against diverted branch HDAWG_V2_Verification:
    - the following functions match:
        - _find_valid_delays
        - _set_dio_delay
        - ensure_symmetric_strobe
        - calibrate_dio_protocol(self, awgs_and_sequences, verbose=False)
        - _get_edges
        - _is_dio_strb_symmetric
        - _analyze_dio_data
    - the following were already commented out here:
        - _check_protocol
        - _print_check_protocol_error_message
        - calibrate_dio
        - calibrate_dio_protocol(self)
    So we conclude all relevant changes of HDAWG_V2_Verification made it here,
    albeit in a different order that clutters the diff.
- removed the above mentioned 4 functions that were commented out
- added comments, organized code into sections
- made some functions 'private'
- NB: none of the above should change anything for real
- moved enabling of outputs to end in configure_codeword_protocol

20190207 WJV
- added assure_ext_clock()

"""

from . import zishell_NH as zs
from .ZI_base_instrument import ZI_base_instrument
from qcodes.utils import validators as vals
from qcodes.instrument.parameter import ManualParameter
import time
import logging
import os
import numpy as np
from zlib import crc32
import ctypes
from ctypes.wintypes import MAX_PATH


class ZI_HDAWG8(ZI_base_instrument):
    """
    This is PycQED/QCoDeS driver driver for the Zurich Instruments HD AWG-8.

    Parameter files are generated from the python API of the instrument
    using the "create_parameter_file" method in the ZI_base_instrument class.
    These are used to add parameters to the instrument.
    """

    ##########################################################################
    # 'public' functions: device control
    ##########################################################################

    def __init__(self, name, device: str,
                 server: str='localhost', port=8004,
                 num_codewords: int = 32, **kw):
        '''
        Input arguments:
            name:           (str) name of the instrument as seen by the user
            device          (str) the name of the device e.g., "dev8008"
            server          (str) the ZI data server
            port            (int) the port to connect to
        '''
        t0 = time.time()
        self._num_codewords = num_codewords

        if os.name == 'nt':
            dll = ctypes.windll.shell32
            buf = ctypes.create_unicode_buffer(MAX_PATH + 1)
            if dll.SHGetSpecialFolderPathW(None, buf, 0x0005, False):
                _basedir = buf.value
            else:
                logging.warning('Could not extract my documents folder')
        else:
            _basedir = os.path.expanduser('~')
        self.lab_one_webserver_path = os.path.join(
            _basedir, 'Zurich Instruments', 'LabOne', 'WebServer')

        super().__init__(name=name, **kw)
        self._devname = device
        self._dev = zs.ziShellDevice()
        self._dev.connect_server(server, port)
        print("Trying to connect to device {}".format(self._devname))
        self._dev.connect_device(self._devname, '1GbE')

        dir_path = os.path.dirname(os.path.abspath(__file__))
        base_fn = os.path.join(dir_path, 'zi_parameter_files')

        try:
            self.add_parameters_from_file(
                filename=os.path.join(base_fn, 'node_doc_HDAWG8.json'))
        except FileNotFoundError:
            logging.warning("parameter file for data parameters"
                            " {} not found".format(self._d_file_name))
            # FIXME: fatal?

        self._add_ZIshell_device_methods_to_instrument()

        dev_type = self.get('features_devtype')
        if dev_type == 'HDAWG8':
            self._num_channels = 8
        elif dev_type == 'HDAWG4':
            self._num_channels = 4
        else:
            self._num_channels = 8
            logging.warning('Unknown device type. Assuming eight channels.')    # FIXME: error?

        self._add_codeword_parameters()
        self._add_extra_parameters()
        self.connect_message(begin_time=t0)

    def get_idn(self):
        # FIXME, update using new parameters for this purpose
        idn_dict = {'vendor': 'ZurichInstruments',
                    'model': self._dev.daq.getByte(
                        '/{}/features/devtype'.format(self._devname)),
                    'serial': self._devname,
                    'firmware': self._dev.geti('system/fwrevision'),
                    'fpga_firmware': self._dev.geti('system/fpgarevision')
                    }
        return idn_dict

    def assure_ext_clock(self):
        """
        Make sure the instrument is using an external reference clock

        Based on: AWG8_V2_DIO_Calibrarion.ipynb
        """

        # get source:
        #   1: external
        #   0: internal (commanded so, or because of failure to sync to ext)
        source = self.system_clocks_referenceclock_source()
        if source == 1:
            return

        print('Switching to external clock. This could take a while!')
        while True:
            self.system_clocks_referenceclock_source(1)
            while True:
                # get status:
                #   0: synced
                #   1: sync failed (will force clock source to internal and retry)
                #   2: syncing
                status = self.system_clocks_referenceclock_status()
                if status == 0:             # synced
                    break
                elif status == 2:           # syncing
                    print('.', end='')
                else:                       # sync failed
                    print('X', end='')
                time.sleep(0.1)
            if self.system_clocks_referenceclock_source() != 1:
                print(' Switching to external clock failed. Trying again.')
            else:
                break
        print('\nDone')

    def stop(self):
        """
        Stops the program on all AWG's part of this AWG8 unit
        """
        for i in range(int(self._num_channels/2)):
            self.set('awgs_{}_enable'.format(i), 0)

    def start(self):
        """
        Starts the program on all AWG's part of this AWG8 unit
        """
        for i in range(int(self._num_channels/2)):
            self.set('awgs_{}_enable'.format(i), 1)

    def snapshot_base(self, update=False, params_to_skip_update=None):
        if params_to_skip_update is None:
            params_to_skip_update = self._params_to_skip_update
        snap = super().snapshot_base(
            update=update, params_to_skip_update=params_to_skip_update)
        return snap

    ##########################################################################
    # 'public' functions: generic AWG/waveform support
    ##########################################################################

    def configure_awg_from_string(self, awg_nr: int, program_string: str,
                                  timeout: float=15):
        """
        Uploads a program string to one of the AWGs of the AWG8.
        """
        self._dev.configure_awg_from_string(awg_nr=awg_nr,
                                            program_string=program_string,
                                            timeout=timeout)
        hash = crc32(program_string.encode('utf-8'))
        self.set('awgs_{}_sequencer_program_crc32_hash'.format(awg_nr),
                 hash)

    def upload_waveform_realtime(self, w0, w1, awg_nr: int, wf_nr: int =1):
        """
        Warning! This method should be used with care.
        Uploads a waveform to the awg in realtime, note that this gets
        overwritten if a new program is uploaded.

        Arguments:
            w0   (array): waveform for ch0 of the awg pair.
            w1   (array): waveform for ch1 of the awg pair.
            awg_nr (int): awg_nr indicating what awg pair to use.
            wf_nr  (int): waveform in memory to overwrite, default is 1.

        There are a few important notes when using this method
        - w0 and w1 must be of the same length
        - any parts of a waveform longer than w0/w1 will not be overwritten.
        - loading speed depends on the size of w0 and w1 and is ~80ms for 20us.

        """
        # these two attributes are added for debugging purposes.
        # they allow checking what the realtime loaded waveforms are.
        self._realtime_w0 = w0
        self._realtime_w1 = w1

        c = np.vstack((w0, w1)).reshape((-2,), order='F')
        self._dev.seti('awgs/{}/waveform/index'.format(awg_nr), wf_nr)
        self._dev.setv('awgs/{}/waveform/data'.format(awg_nr), c)
        self._dev.seti('awgs/{}/enable'.format(awg_nr), wf_nr)

    ##########################################################################
    # 'public' functions: application specific/codeword support
    ##########################################################################

    def initialze_all_codewords_to_zeros(self):
        """
        Generates all zeros waveforms for all codewords
        """
        t0 = time.time()
        wf = np.zeros(32)
        waveform_params = [value for key, value in self.parameters.items()
                           if 'wave_ch' in key.lower()]
        for par in waveform_params:
            par(wf)
        t1 = time.time()
        print('Set all zeros waveforms in {:.1f} s'.format(t1-t0))

    def upload_codeword_program(self, awgs=np.arange(4)):
        """
        Generates a program that plays the codeword waves for each channel.

        awgs (array): the awg numbers to which to upload the codeword program.
                    By default uploads to all channels but can be specific to
                    speed up the process.
        """
        # Type conversion to ensure lists do not produce weird results
        awgs = np.array(awgs)
        # because awg_channels come in pairs and are numbered from 1-8 in API
        awg_channels = awgs*2+1

        for awg_nr in awgs:
            # disable all AWG channels
            self.set('awgs_{}_enable'.format(int(awg_nr)), 0)

        codeword_mode_snippet = (
            'while (1) { \n '
            '\t// Wait for a trigger on the DIO interface\n'
            '\twaitDIOTrigger();\n'
            '\t// Play a waveform from the table based on the DIO code-word\n'
            '\tplayWaveDIO(); \n'
            '}')
        if self.cfg_codeword_protocol() != 'flux':
            # FIXME: this is a catchall
            for ch in awg_channels:
                waveform_table = '// Define the waveform table\n'
                for cw in range(self.cfg_num_codewords()):
                    wf0_name = '{}_wave_ch{}_cw{:03}'.format(
                        self._devname, ch, cw)
                    wf1_name = '{}_wave_ch{}_cw{:03}'.format(
                        self._devname, ch+1, cw)
                    waveform_table += 'setWaveDIO({}, "{}", "{}");\n'.format(
                        cw, wf0_name, wf1_name)
                program = waveform_table + codeword_mode_snippet
                # N.B. awg_nr in goes from 0 to 3 in API while in LabOne
                # it is 1 to 4
                awg_nr = ch//2  # channels are coupled in pairs of 2
                self.configure_awg_from_string(awg_nr=int(awg_nr),
                                               program_string=program,
                                               timeout=self.timeout())
        else:  # if protocol is flux
            for ch in awg_channels:
                waveform_table = '//Flux mode\n// Define the waveform table\n'
                mask_0 = 0b000111  # AWGx_ch0 uses lower bits for CW
                mask_1 = 0b111000  # AWGx_ch1 uses higher bits for CW

                # for cw in range(2**6):
                for cw in range(8):
                    cw0 = cw & mask_0
                    cw1 = (cw & mask_1) >> 3
                    if 1:
                        # FIXME: this is a hack because not all AWG8 channels support
                        # amp mode. It forces all AWGs of a pair to behave identical.
                        cw1 = cw0
                        # FIXME: the above is no longer true
                        logger.warning('applied outdated flux channel duplication hack')
                    # if both wfs are triggered play both
                    if (cw0 != 0) and (cw1 != 0):
                        # if both waveforms exist, upload
                        wf0_cmd = '"{}_wave_ch{}_cw{:03}"'.format(
                            self._devname, ch, cw0)
                        wf1_cmd = '"{}_wave_ch{}_cw{:03}"'.format(
                            self._devname, ch+1, cw1)

                    # if single wf is triggered fill the other with zeros
                    elif (cw0 == 0) and (cw1 != 0):
                        wf0_cmd = 'zeros({})'.format(len(self.get(
                            'wave_ch{}_cw{:03}'.format(ch, cw1))))
                        wf1_cmd = '"{}_wave_ch{}_cw{:03}"'.format(
                            self._devname, ch+1, cw1)

                    elif (cw0 != 0) and (cw1 == 0):
                        wf0_cmd = '"{}_wave_ch{}_cw{:03}"'.format(
                            self._devname, ch, cw0)
                        wf1_cmd = 'zeros({})'.format(len(self.get(
                            'wave_ch{}_cw{:03}'.format(ch, cw0))))
                    # if no wfs are triggered play only zeros
                    else:
                        wf0_cmd = 'zeros({})'.format(48)
                        wf1_cmd = 'zeros({})'.format(48)

                    waveform_table += 'setWaveDIO({}, {}, {});\n'.format(
                        cw, wf0_cmd, wf1_cmd)
                program = waveform_table + codeword_mode_snippet

                # N.B. awg_nr in goes from 0 to 3 in API while in LabOne it
                # is 1 to 4
                awg_nr = ch//2  # channels are coupled in pairs of 2
                self.configure_awg_from_string(awg_nr=int(awg_nr),
                                               program_string=program,
                                               timeout=self.timeout())
        self.configure_codeword_protocol()

    # FIXME: should probably be private as it works in tandem with upload_codeword_program
    def configure_codeword_protocol(self, default_dio_timing: bool=False):
        """
        This method configures the AWG-8 codeword protocol.
        The final step enables the signal output of each AWG and sets
        it to the right mode.

        The parameter "cfg_codeword_protocol" defines what protocol is used.
        There are three options:
            identical : all AWGs have the same configuration
            microwave : AWGs 0 and 1 share bits
            flux      : Each AWG pair is responsible for 2 flux channels.
                        this also affects the "codeword_program" and
                        setting "wave_chX_cwXXX" parameters.

        """

        # Configure the DIO interface
        for awg_nr in range(int(self._num_channels/2)):
            # Set the bit index of the valid bit
            self.set('awgs_{}_dio_valid_index'.format(awg_nr), 31)

            # Set polarity of the valid bit:
            # 2: 'high', 1: 'low', 0: 'no valid needed'
            self.set('awgs_{}_dio_valid_polarity'.format(awg_nr), 2)

            # Set the bit index of the strobe signal (TOGGLE_DS),
            self.set('awgs_{}_dio_strobe_index'.format(awg_nr), 30)

            # Configure edge triggering for the strobe/toggle bit signal:
            # 1: rising edge, 2: falling edge or 3: both edges
            self.set('awgs_{}_dio_strobe_slope'.format(awg_nr), 3)

            # the mask determines how many bits will be used in the protocol
            # e.g., mask 3 will mask the bits with bin(3) = 00000011 using
            # only the 2 Least Significant Bits.
            # N.B. cfg_num_codewords must be a power of 2
            self.set('awgs_{}_dio_mask_value'.format(awg_nr),
                     self.cfg_num_codewords()-1)

            if self.cfg_codeword_protocol() == 'identical':
                # In the identical protocol all bits are used to trigger
                # the same codewords on all AWG's

                # N.B. The shift is applied before the mask
                # The relevant bits can be selected by first shifting them
                # and then masking them.
                self.set('awgs_{}_dio_mask_shift'.format(awg_nr), 0)
            elif self.cfg_codeword_protocol() == 'microwave':
                # In the mw protocol bits [0:7] -> CW0 and bits [(8+1):15] -> CW1
                # N.B. DIO bit 8 (first of 2nd byte)  not connected in AWG8!
                if awg_nr in [0, 1]:
                    self.set('awgs_{}_dio_mask_shift'.format(awg_nr), 0)
                elif awg_nr in [2, 3]:
                    self.set('awgs_{}_dio_mask_shift'.format(awg_nr), 9)    # FIXME: this is no longer true for HDAWG V2
            elif self.cfg_codeword_protocol() == 'flux':
                # bits[0:3] for awg0_ch0, bits[4:6] for awg0_ch1 etc.
                # self.set('awgs_{}_dio_mask_value'.format(awg_nr), 2**6-1)
                # self.set('awgs_{}_dio_mask_shift'.format(awg_nr), awg_nr*6)

                # FIXME: this is a protocol that does identical flux pulses
                # on each channel.
                self.set('awgs_{}_dio_mask_value'.format(awg_nr), 2**3-1)
                # self.set('awgs_{}_dio_mask_shift'.format(awg_nr), 3)
                self.set('awgs_{}_dio_mask_shift'.format(awg_nr), 0)
            else:
                logging.error('unknown value for cfg_codeword_protocol')
                # FIXME: exception?

        # Disable all function generators
        self._dev.daq.setInt('/' + self._dev.device +
                             '/sigouts/*/enables/*', 0)

        # Set amp or direct mode
        if self.cfg_codeword_protocol() == 'flux':
            # when doing flux pulses, set everything to amp mode
            for ch in range(8):
                self.set('sigouts_{}_direct'.format(ch), 0)
                self.set('sigouts_{}_range'.format(ch), 5)
        else:
            # Switch all outputs into direct mode when not using flux pulses
            for ch in range(8):
                self.set('sigouts_{}_direct'.format(ch), 1)
                self.set('sigouts_{}_range'.format(ch), .8)

        # Enable AWGs
        time.sleep(.05) # FIXME: why?
        self._dev.daq.setInt('/' + self._dev.device +
                             '/awgs/*/enable', 1)

        # Turn on all outputs
        self._dev.daq.setInt('/' + self._dev.device + '/sigouts/*/on', 1)


    def calibrate_dio_protocol(self, awgs_and_sequences, verbose=False):
        if verbose:
            print("INFO   : Calibrating DIO delays")

        if not self._ensure_symmetric_strobe(verbose):
            if verbose:
                print("ERROR  : Strobe is not symmetric!")
            return False
        else:
            if verbose:
                print("INFO   : Strobe is symmetric")

        all_valid_delays = []
        for awg, sequence in awgs_and_sequences:
            valid_delays = self._find_valid_delays(awg, sequence, verbose)
            if valid_delays:
                all_valid_delays.append(valid_delays)
            else:
                if verbose:
                    print(
                        "ERROR  : Unable to find valid delays for AWG {}!".format(awg))
                return False

        # Figure out which delays are valid
        combined_valid_delays = set.intersection(*all_valid_delays)
        max_valid_delay = max(combined_valid_delays)

        # Print information
        if verbose:
            print("INFO   : Valid delays are {}".format(combined_valid_delays))
        if verbose:
            print("INFO   : Setting delay to {}".format(max_valid_delay))

        # And configure the delays
        for awg, _ in awgs_and_sequences:
            vld_mask = 1 << self._dev.geti(
                'awgs/{}/dio/valid/index'.format(awg))
            strb_mask = 1 << self._dev.geti(
                'awgs/{}/dio/strobe/index'.format(awg))
            cw_mask = self._dev.geti('awgs/{}/dio/mask/value'.format(awg))
            cw_shift = self._dev.geti('awgs/{}/dio/mask/shift'.format(awg))
            if verbose:
                print("INFO   : Setting delay of AWG {}".format(awg))
            self._set_dio_delay(
                awg, strb_mask,
                (cw_mask << cw_shift) | vld_mask, max_valid_delay)

        return True

    ##########################################################################
    # 'private' functions, internal to the driver
    ##########################################################################

    def _add_ZIshell_device_methods_to_instrument(self):
        """
        Some methods defined in the zishell are convenient as public
        methods of the instrument. These are added here.
        """
        self.reconnect = self._dev.reconnect
        self.restart_device = self._dev.restart_device
        self.poll = self._dev.poll
        self.sync = self._dev.sync
        self.read_from_scope = self._dev.read_from_scope
        self.restart_scope_module = self._dev.restart_scope_module
        self.restart_awg_module = self._dev.restart_awg_module

    def _add_extra_parameters(self):
        self.add_parameter('timeout', unit='s',
                           initial_value=10,
                           parameter_class=ManualParameter)
        self.add_parameter(
            'cfg_num_codewords', label='Number of used codewords', docstring=(
                'This parameter is used to determine how many codewords to '
                'upload in "self.upload_codeword_program".'),
            initial_value=self._num_codewords,
            # FIXME: commented out numbers larger than self._num_codewords
            # see also issue #358
            vals=vals.Enum(2, 4, 8, 16, 32),  # , 64, 128, 256, 1024),
            parameter_class=ManualParameter)

        self.add_parameter(
            'cfg_codeword_protocol', initial_value='identical',
            vals=vals.Enum('identical', 'microwave', 'flux'), docstring=(
                'Used in the configure codeword method to determine what DIO'
                ' pins are used in for which AWG numbers.'),
            parameter_class=ManualParameter)

        for i in range(4):
            self.add_parameter(
                'awgs_{}_sequencer_program_crc32_hash'.format(i),
                parameter_class=ManualParameter,
                initial_value=0, vals=vals.Ints())

    def _add_codeword_parameters(self):
        """
        Adds parameters that are used for uploading codewords.
        It also contains initial values for each codeword to ensure
        that the "upload_codeword_program" ... FIXME: comment ends

        """
        docst = ('Specifies a waveform to for a specific codeword. ' +
                 'The waveforms must be uploaded using ' +
                 '"upload_codeword_program". The channel number corresponds' +
                 ' to the channel as indicated on the device (1 is lowest).')
        self._params_to_skip_update = []
        for ch in range(self._num_channels):
            for cw in range(self._num_codewords):
                parname = 'wave_ch{}_cw{:03}'.format(ch+1, cw)
                self.add_parameter(
                    parname,
                    label='Waveform channel {} codeword {:03}'.format(
                        ch+1, cw),
                    vals=vals.Arrays(),  # min_value, max_value = unknown
                    set_cmd=self._gen_write_csv(parname),
                    get_cmd=self._gen_read_csv(parname),
                    docstring=docst)
                self._params_to_skip_update.append(parname)

    def _gen_write_csv(self, wf_name):
        def write_func(waveform):
            # The length of AWG8 waveforms should be a multiple of 8 samples.
            if (len(waveform) % 8) != 0:
                extra_zeros = 8-(len(waveform) % 8)
                waveform = np.concatenate([waveform, np.zeros(extra_zeros)])
            return self._write_csv_waveform(
                wf_name=wf_name, waveform=waveform)
        return write_func

    def _write_csv_waveform(self, wf_name: str, waveform):
        filename = os.path.join(
            self.lab_one_webserver_path, 'awg', 'waves',
            self._devname+'_'+wf_name+'.csv')
        with open(filename, 'w') as f:
            np.savetxt(filename, waveform, delimiter=",")

    def _gen_read_csv(self, wf_name):
        def read_func():
            return self._read_csv_waveform(
                wf_name=wf_name)
        return read_func

    def _read_csv_waveform(self, wf_name: str):
        filename = os.path.join(
            self.lab_one_webserver_path, 'awg', 'waves',
            self._devname+'_'+wf_name+'.csv')
        try:
            return np.genfromtxt(filename, delimiter=',')
        except OSError as e:
            # if the waveform does not exist yet dont raise exception
            logging.warning(e)
            print(e)
            return None

    ##########################################################################
    # 'private' functions: helpers for calibrate_dio_protocol()
    ##########################################################################

    def _ensure_symmetric_strobe(self, verbose=False):
        done = False
        good_shots = 0
        bad_shots = 0
        strb_bits = []
        for awg in range(0, 4):
            strb_bits.append(self._dev.geti(
                'awgs/{}/dio/strobe/index'.format(awg)))
        strb_bits = list(set(strb_bits))
        if verbose:
            print('INFO   : Analyzing strobe bits {}'.format(strb_bits))

        while not done:
            data = self._dev.getv('raw/dios/0/data')
            if _is_dio_strb_symmetric(data, strb_bits):
                if verbose:
                    print('INFO   : Found good shot')
                bad_shots = 0
                good_shots += 1
                if good_shots > 5:
                    done = True
            else:
                if verbose:
                    print('INFO   : Strobe bit(s) are not sampled symmetrically')
                if verbose:
                    print("INFO   :   Disabling AWG's")

                # save enabled state of AWGs, then disable them
                enables = 4*[0]
                for awg in range(0, 4):
                    enables[awg] = self._dev.geti('awgs/{}/enable'.format(awg))
                    self._dev.seti('awgs/{}/enable'.format(awg), 0)

                # switch clock to internal and back to external
                if verbose:
                    print("INFO   :   Switching to internal clock")
                self.system_clocks_referenceclock_source(0)
                time.sleep(5)
                if verbose:
                    print("INFO   :   Switching to external clock")
                self.system_clocks_referenceclock_source(1)
                time.sleep(5)
                # FIXME: check locking

                # restore enabled state of AWGs
                if verbose:
                    print("INFO   :   Enabling AWG's")
                for awg in range(0, 4):
                    self._dev.seti('awgs/{}/enable'.format(awg), enables[awg])

                good_shots = 0
                bad_shots += 1
                if bad_shots > 5:
                    done = True

        return (good_shots > 0) and (bad_shots == 0)

    def _find_valid_delays(self, awg, expected_sequence, verbose=False):
        """
        The function loops through the possible delay settings on the DIO interface
        and records and analyzes DIO data for each setting. It then determines whether
        a given delay setting results in valid DIO protocol data being recorded.
        In order for data to be correct, two conditions must be satisfied: First,
        no timing violations are allowed, and, second, the sequence of codewords
        detected on the interface must match the expected sequence.
        """
        if verbose:
            print("INFO   : Finding valid delays for AWG {}".format(awg))
        vld_mask = 1 << self._dev.geti('awgs/{}/dio/valid/index'.format(awg))
        vld_polarity = self._dev.geti('awgs/{}/dio/valid/polarity'.format(awg))
        strb_mask = 1 << self._dev.geti('awgs/{}/dio/strobe/index'.format(awg))
        strb_slope = self._dev.geti('awgs/{}/dio/strobe/slope'.format(awg))
        cw_mask = self._dev.geti('awgs/{}/dio/mask/value'.format(awg))
        cw_shift = self._dev.geti('awgs/{}/dio/mask/shift'.format(awg))

        if verbose:
            print('INFO   : vld_mask     = 0x{:08x}'.format(vld_mask))
            print('INFO   : vld_polarity =', vld_polarity)
            print('INFO   : strb_mask    = 0x{:08x}'.format(strb_mask))
            print('INFO   : strb_slope   =', strb_slope)
            print('INFO   : cw_mask      = 0x{:08x}'.format(cw_mask))
            print('INFO   : cw_shift     =', cw_shift)

        valid_delays = []
        for delay in range(0, 7):
            if verbose:
                print("INFO   : Testing delay {} on AWG {}...".format(delay, awg))
            self._set_dio_delay(awg, strb_mask,
                                (cw_mask << cw_shift) | vld_mask, delay)

            data = self._dev.getv('awgs/' + str(awg) + '/dio/data')
            codewords, timing_violations = _analyze_dio_data(
                data, strb_mask, strb_slope, vld_mask, vld_polarity, cw_mask, cw_shift)
            timeout_cnt = 0
            while (cw_mask != 0) and len(codewords) == 0:
                if timeout_cnt > 5:
                    break
                if verbose:
                    print("WARNING: No codewords detected, trying again!")
                data = self._dev.getv('awgs/' + str(awg) + '/dio/data')
                codewords, timing_violations = _analyze_dio_data(
                    data, strb_mask, strb_slope, vld_mask, vld_polarity, cw_mask, cw_shift)
                timeout_cnt += 1

            # Compare codewords against sequence
            if (cw_mask != 0) and len(codewords) == 0:
                if verbose:
                    print(
                        "WARNING: No codewords detected on AWG {} for delay {}".format(awg, delay))
                continue

            # Can't do nothing with timing violations
            if timing_violations:
                if verbose:
                    print("WARNING: Timing violation detected on AWG {} for delay {}!".format(
                        awg, delay))
                continue

            # Check against expected sequence
            valid_sequence = True
            for n, codeword in enumerate(codewords):
                if n == 0:
                    if codeword not in expected_sequence:
                        if verbose:
                            print("WARNING: Codeword {} with value {} not in expected sequence {}!".format(
                                n, codeword, expected_sequence))
                        if verbose:
                            print(
                                "INFO   : Detected codeword sequence: {}".format(codewords))
                        valid_sequence = False
                        break
                    else:
                        index = expected_sequence.index(codeword)
                else:
                    last_index = index
                    index = (index + 1) % len(expected_sequence)
                    if codeword != expected_sequence[index]:
                        if verbose:
                            print("WARNING: Codeword {} with value {} not expected to follow codeword {} in expected sequence {}!".format(
                                n, codeword, expected_sequence[last_index], expected_sequence))
                        if verbose:
                            print(
                                "INFO   : Detected codeword sequence: {}".format(codewords))
                        valid_sequence = False
                        break

            # If we get to this point the delay is valid
            if valid_sequence:
                valid_delays.append(delay)

        if verbose:
            print("INFO   : Found valid delays of {}".format(list(valid_delays)))
        return set(valid_delays)


    def _set_dio_delay(self, awg, strb_mask, data_mask, delay):
        """
        The function sets the DIO delay for a given FPGA. The valid delay range is
        0 to 6. The delays are created by either delaying the data bits or the strobe
        bit. The data_mask input represents all bits that are part of the codeword or
        the valid bit. The strb_mask input represents the bit that define the strobe.
        """
        if delay < 0:
            print('WARNING: Clamping delay to 0')
        if delay > 6:
            print('WARNING: Clamping delay to 6')
            delay = 6

        strb_delay = 0
        data_delay = 0
        if delay > 3:
            strb_delay = delay-3
        else:
            data_delay = 3-delay

        for i in range(32):
            self._dev.seti('awgs/{}/dio/delay/index'.format(awg), i)
            if strb_mask & (1 << i):
                self._dev.seti(
                    'awgs/{}/dio/delay/value'.format(awg), strb_delay)
            elif data_mask & (1 << i):
                self._dev.seti(
                    'awgs/{}/dio/delay/value'.format(awg), data_delay)
            else:
                self._dev.seti('awgs/{}/dio/delay/value'.format(awg), 0)

##############################################################################
# non class functions: helpers for calibrate_dio_protocol()
##############################################################################

def _get_edges(value, last_value, mask):
    """
    Given two integer values representing a current and a past value,
    and a bit mask, this function will return two
    integer values representing the bits with rising (re) and falling (fe)
    edges.
    """
    changed = value ^ last_value
    re = changed & value & mask
    fe = changed & ~value & mask
    return re, fe


def _is_dio_strb_symmetric(data, bits):
    count_ok = True

    for bit in bits:
        strobe_mask = 1 << bit
        count_low = False
        count_high = False
        strobe_low = 0
        strobe_high = 0
        last_strobe = None
        for n, d in enumerate(data):
            curr_strobe = (d & strobe_mask) != 0

            if count_high:
                if curr_strobe:
                    strobe_high += 1
                else:
                    if (strobe_low > 0) and (strobe_low != strobe_high):
                        count_ok = False
                        break

            if count_low:
                if not curr_strobe:
                    strobe_low += 1
                else:
                    if (strobe_high > 0) and (strobe_low != strobe_high):
                        count_ok = False
                        break

            if (last_strobe != None):
                if (curr_strobe and not last_strobe):
                    strobe_high = 0
                    count_high = True
                    count_low = False
                elif (not curr_strobe and last_strobe):
                    strobe_low = 0
                    count_low = True
                    count_high = False

            last_strobe = curr_strobe

        if not count_ok:
            break

    return count_ok


def _analyze_dio_data(data, strb_mask, strb_slope, vld_mask, vld_polarity, cw_mask, cw_shift):
    """
    Analyzes a list of integer values that represent samples recorded on the DIO interface.
    The function needs information about the protocol used on the DIO interface. Based
    on this information the function will return two lists: the detected codewords
    and the positions where 'timing violations' are found. The codewords are sampled
    according to the protocol configuration. Timing violations occur when a codeword
    bit or the valid bit changes value at the same time as the strobe signal.
    """
    timing_violations = []
    codewords = []
    last_d = None
    for n, d in enumerate(data):
        if n > 0:
            strb_re = False
            strb_fe = False
            if strb_slope == 0:
                strb_re = True
                strb_fe = True
            elif strb_slope == 1:
                strb_re, _ = _get_edges(d, last_d, strb_mask)
            elif strb_slope == 2:
                _, strb_fe = _get_edges(d, last_d, strb_mask)
            else:
                strb_re, strb_fe = _get_edges(d, last_d, strb_mask)

            vld_re = False
            vld_fe = False
            if vld_polarity != 0:
                vld_re, vld_fe = _get_edges(d, last_d, vld_mask)

            d_re = False
            d_fe = False
            if cw_mask != 0:
                d_re, d_fe = _get_edges(d, last_d, cw_mask << cw_shift)

            vld_active = ((vld_polarity & 1) and ((d & vld_mask) == 0)) or (
                (vld_polarity & 2) and ((d & vld_mask) != 0))
            codeword = (d >> cw_shift) & cw_mask

            # Check for timing violation on vld
            if (strb_re or strb_fe) and (vld_re or vld_fe):
                timing_violations.append(n)
            elif (strb_re or strb_fe) and (d_re or d_fe):
                timing_violations.append(n)

            # Get the codewords
            if (strb_re or strb_fe) and vld_active:
                codewords.append(codeword)

        last_d = d

    return codewords, timing_violations
