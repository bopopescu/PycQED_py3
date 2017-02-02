"""
Final layout
"""
from pycqed.scripts.Experiments.Five_Qubits import CZ_tuneup as czt

"""
RO tune-up
"""

MC = qc.station.MC
LutManMan = qc.station.components['LutManMan']

list_qubits = [q0, q1, q2, q3, q4]
for q in list_qubits:
    q.RO_acq_averages(2**10)
    q.pulse_I_offset(0.001)
    q.pulse_Q_offset(-0.006)
    q.RO_I_offset(11e-3)
    q.RO_Q_offset(15e-3)


# preparing the multiplexed readout pulse
integration_length = 550e-9
pulse_length = 450e-9
chi = 2.5e6
M_amps = [0.2, 0.2, 0.0, 0.00, 0.0]
f_ROs = [7.599e9, 7.095e9, 7.787e9, 7.085e9, 7.998e9]

# configuring the readout LO frequency
LO_frequency = f_ROs[1]+380e6

for i in range(5):
    LutMan = eval('LutMan{}'.format(i))
    q = list_qubits[i]
    # Defined in the init
    switch_to_IQ_mod_RO_UHFQC(q)
    q.RO_acq_weight_function_I(i)
    q.RO_acq_weight_function_Q(i)
    q.RO_acq_integration_length(integration_length)
    q.RO_amp(M_amps[i])
    q.f_RO(f_ROs[i])
    q.f_RO_mod(q.f_RO()-LO_frequency)
    LutMan.M_modulation(q.f_RO()-LO_frequency)
    LutMan.M0_modulation(LutMan.M_modulation()+chi)
    LutMan.M1_modulation(LutMan.M_modulation()-chi)
    LutMan.Q_modulation(0)
    LutMan.Q_amp180(0.8/2)
    LutMan.M_up_amp(M_amps[i])
    LutMan.Q_gauss_width(100e-9)
    LutMan.Q_motzoi_parameter(0)
    LutMan.M_amp(M_amps[i])
    LutMan.M_down_amp0(0.0/2)
    LutMan.M_down_amp1(0.0/2)
    LutMan.M_length(pulse_length-100e-9)
    LutMan.M_up_length(100.0e-9)
    LutMan.M_down_length(1e-9)
    LutMan.Q_gauss_nr_sigma(5)
    LutMan.acquisition_delay(270e-9)

multiplexed_wave = [['LutMan0', 'M_up_mid_double_dep'],
                    ['LutMan1', 'M_up_mid_double_dep'],
                    ['LutMan2', 'M_up_mid_double_dep'],
                    ['LutMan3', 'M_up_mid_double_dep'],
                    ['LutMan4', 'M_up_mid_double_dep'],
                    ]

LutManMan.generate_multiplexed_pulse(multiplexed_wave)
LutManMan.render_wave('Multiplexed_pulse', time_units='s')
LutManMan.render_wave_PSD(
    'Multiplexed_pulse', f_bounds=[00e6, 1000e6], y_bounds=[1e-18, 1e-6])
LutManMan.load_pulse_onto_AWG_lookuptable('Multiplexed_pulse')

# configuring a joint qubit gate LO
Qubit_LO_frequency = q0.f_qubit()+0.05e9
q0.f_pulse_mod(q0.f_qubit()-Qubit_LO_frequency)
q1.f_pulse_mod(q1.f_qubit()-Qubit_LO_frequency)
q2.f_pulse_mod(q2.f_qubit()-Qubit_LO_frequency)
q3.f_pulse_mod(q3.f_qubit()-Qubit_LO_frequency)
q4.f_pulse_mod(q4.f_qubit()-Qubit_LO_frequency)

MC.soft_avg(1)



###########################################
# integration weight function tune-up
###########################################
cal_shots = 4094
MC.soft_avg(1)
# calibrating the weight functions and measuring individual SSRO
for q in [q0, q1]:

    q.measure_ssro(SSB=True, optimized_weights=True,
                    nr_shots=cal_shots, one_weight_function_UHFQC=True)
    print('LO freq: {:.4f} GHz'.format(LO.frequency()*1e-9))
    print('Drive freq: {:.4f} GHz'.format(Qubit_LO.frequency()*1e-9))


# measuring the multiplexed SSRO result of all four states and uploading
# the cross-talk suippression matrix
tune_up_shots = 2**14
# reload(awg_swf_m)
# reload(sq_m)
sq_m.station = station # multi qubit sequences
q0_pulse_pars, RO_pars = q0.get_pulse_pars()
q1_pulse_pars, RO_pars_q1 = q1.get_pulse_pars()

detector = det.UHFQC_integration_logging_det(
    UHFQC=UHFQC_1, AWG=AWG,
    channels=[0, 1, 2, 3],
    integration_length=integration_length, nr_shots=2048)
sweep = awg_swf_m.two_qubit_off_on(
    q0_pulse_pars=q0_pulse_pars, q1_pulse_pars=q1_pulse_pars, RO_pars=RO_pars)
MC.set_sweep_function(sweep)
MC.set_sweep_points(np.arange(tune_up_shots))
MC.set_detector_function(detector)
label = 'Two_qubit_SSRO_tuneup'
MC.run(label)
mu_matrix,  V_th, mu_matrix_inv, V_th_cor,  V_offset_cor = Niels.two_qubit_ssro_fidelity(
    label, fig_format='png')

UHFQC_1.quex_trans_offset_weightfunction_0(V_offset_cor[0])
UHFQC_1.quex_trans_offset_weightfunction_1(V_offset_cor[1])
UHFQC_1.upload_transformation_matrix(mu_matrix_inv)


###################################################
# Verification of the results
###################################################
tune_up_shots=2**14
sq_m.station=station
q0_pulse_pars, RO_pars=q0.get_pulse_pars()
q1_pulse_pars, RO_pars_q1=q1.get_pulse_pars()

detector = det.UHFQC_integration_logging_det(
                UHFQC=UHFQC_1, AWG=AWG,
                channels=[0,1,2,3],
                integration_length=integration_length, nr_shots=2048, cross_talk_suppression=True)
sweep = awg_swf_m.two_qubit_off_on(
    q0_pulse_pars=q0_pulse_pars,q1_pulse_pars=q1_pulse_pars, RO_pars=RO_pars)
MC.set_sweep_function(sweep)
MC.set_sweep_points(np.arange(tune_up_shots))
MC.set_detector_function(detector)
label ='Two_qubit_SSRO_check'
MC.run(label)
mu_matrix,  V_th, mu_matrix_inv, V_th_cor,  V_offset_cor=Niels.two_qubit_ssro_fidelity(label, fig_format='png')
print("residual cross-talk matrix",  mu_matrix)


###########################################################
# Two qubit AllXY to verify multiplexed driving and RO
#############################################################

# S5 is the device object
mq_mod.measure_two_qubit_AllXY(S5, q0.name, q1.name)

"""
All XY tune-up
"""
SH = sh.SignalHound_USB_SA124B('Signal hound', server_name=None)
qubit_list = [q0, q1]
MC.soft_avg(1)

for qubit in qubit_list:
    qubit.calibrate_mixer_offsets(SH)
    qubit.RO_acq_averages(2**9)
    qubit.find_frequency(method='ramsey', update=True)
    qubit.RO_acq_averages(2**10)
    qubit.find_pulse_amplitude(amps=np.linspace(-1.0, 1.0, 21),
                                    N_steps=[3,7], max_n=100, take_fit_I=True)
    qubit.measure_motzoi_XY(motzois=np.linspace(-0.2, 0.2, 21))
    MC.soft_avg(5)
    qubit.find_pulse_amplitude(amps=np.linspace(-1.0, 1.0, 21),
                               N_steps=[3, 7, 19], max_n=100, take_fit_I=True)
    qubit.find_amp90_scaling(scales=0.5,N_steps=[5, 9], max_n=100,
                             take_fit_I=True)

MC.soft_avg(1)
mq_mod.measure_two_qubit_AllXY(S5, 'DataT', 'AncT')
DataT.measure_allxy()
AncT.measure_allxy()

"""
function definitions
"""
def fix_phase_qcp():
    label = 'SWAP_CP_SWAP'
    a = ma.MeasurementAnalysis(label=label, auto=False)
    a.get_naming_and_values()
    x = a.sweep_points[:-4]
    cp_acq_weight = 0
    y = a.measured_values[cp_acq_weight, :-4]
    return a_tools.find_min(x, y, )


def fix_phase_qs():
    label = 'SWAP_CP_SWAP'
    a = ma.MeasurementAnalysis(label=label, auto=False)
    a.get_naming_and_values()
    x = a.sweep_points[:-4]
    qs_acq_weigth = 1
    y = a.measured_values[qs_acq_weigth, :-4]
    return a_tools.find_min(x, y, )


def fix_phase_2Q():
    label = 'CZ_cost_function'
    a = ma.MeasurementAnalysis(label=label, auto=False)
    a.get_naming_and_values()
    x = a.sweep_points[:]
    cp_acq_weight = 0
    y = a.measured_values[cp_acq_weight, :]
    return x[np.argmax(y)], y[np.argmax(y)]


def get_rSWAP_amp():
    label = 'rSWAP'
    a = ma.MeasurementAnalysis(label=label, auto=False)
    a.get_naming_and_values()
    x = a.sweep_points[:-4]
    qs_acq_weight = 1
    y = a.measured_values[qs_acq_weight, :-4]
    return a_tools.find_min(x,-y)


def fix_swap_amp():
    label = 'SWAP_cost_function'
    a = ma.MeasurementAnalysis(label=label, auto=False)
    a.get_naming_and_values()
    x = a.sweep_points[:]
    y = a.measured_values[0, :]
    return x[np.argmax(y)], y[np.argmax(y)]


def print_CZ_pars(AncT, DataT):
    print('********************************')
    print('CZ Amp = {:.3f} Vpp'.format(AncT.CZ_channel_amp()))
    print('SWAP Amp = {:.3f} Vpp'.format(DataT.SWAP_amp()))
    print(r'ratio rSWAP_amp/SWAP_amp = {:.3f}'.format(DataT.rSWAP_pulse_amp()/DataT.SWAP_pulse_amp()))
    print('qS phase corr = {:.3f}'.format(DataT.SWAP_corr_amp()))
    print('qZ phase corr = {:.3f}'.format(AncT.CZ_corr_amp()))
    print('********************************')

"""
CPhase tuneup STEP 1
Sweeping amplitudes of CZ, SWAP and rSWAP
"""

#######################
# prepares to start
#######################
AWG.ch3_amp(AncT.CZ_channel_amp())
AWG.ch4_amp(DataT.SWAP_amp())
AncT.CZ_corr_amp(0.)
DataT.SWAP_corr_amp(0.)

CZ_amp_vec = []
SWAP_amp_vec = []
rSWAP_amp_vec = []

for i in range(5):
    print_CZ_pars(AncT, DataT)
    # starts a 2Q calibration
    CZ_amps = np.linspace(-0.01, .01, 11) + AncT.CZ_channel_amp()
    AWG.ch4_amp(DataT.SWAP_amp())
    corr_amps = np.arange(.0, .3, 0.01)
    MC.set_sweep_function(AWG.ch3_amp)
    MC.set_sweep_points(CZ_amps)
    d = czt.CPhase_cost_func_det(S5, DataT, AncT, nested_MC, corr_amps)
    MC.set_detector_function(d)
    MC.run('CZ_cost_function')
    ma.MeasurementAnalysis(label='CZ_cost_function')
    AncT.CZ_channel_amp(fix_phase_2Q()[0])
    AWG.ch3_amp(AncT.CZ_channel_amp())
    CZ_amp_vec.append(AncT.CZ_channel_amp())
    print_CZ_pars(AncT, DataT)

    # starts a SWAP calibration
    SWAP_amps = np.linspace(-0.01, .01, 11) + DataT.SWAP_amp()
    corr_amps = np.arange(.0, .3, 0.01)
    MC.set_sweep_function(AWG.ch4_amp)
    MC.set_sweep_points(SWAP_amps)
    d = czt.CPhase_cost_func_det(S5, DataT, AncT, nested_MC, corr_amps)
    MC.set_detector_function(d)
    MC.run('SWAP_cost_function')
    ma.MeasurementAnalysis(label='SWAP_cost_function')
    DataT.SWAP_amp(fix_swap_amp()[0])
    AWG.ch4_amp(DataT.SWAP_amp())
    SWAP_amp_vec.append(DataT.SWAP_amp())
    print_CZ_pars(AncT, DataT)

    # starts a rSWAP calibration
    mq_mod.rSWAP_scan(S5, 'DataT', 'AncT', recovery_swap_amps=np.linspace(0.435, 0.465, 60))
    ma.MeasurementAnalysis(label='rSWAP', auto=True)
    DataT.rSWAP_pulse_amp(get_rSWAP_amp()[0])
    rSWAP_amp_vec.append(DataT.rSWAP_pulse_amp())
    print_CZ_pars(AncT, DataT)

"""
CPhase tuneup STEP 2
Sweeping 1Q phases
"""
AWG.ch3_amp(AncT.CZ_channel_amp())
AWG.ch4_amp(DataT.SWAP_amp())
AncT.CZ_corr_amp(0.)
DataT.SWAP_corr_amp(0.)

# 1Q calibrations
for jj in range(2):
    mq_mod.measure_SWAP_CZ_SWAP(S5, 'DataT', 'AncT',
                                np.linspace(0., -0.25, 60),
                                # need 64 to be same as tomo seq,
                                sweep_qubit='DataT', excitations=0)
    DataT.SWAP_corr_amp(fix_phase_qs()[0])
    print_CZ_pars(AncT, DataT)
    mq_mod.measure_SWAP_CZ_SWAP(S5, 'DataT', 'AncT',
                                np.linspace(0., -0.25, 60),
                                # need 64 to be same as tomo seq,
                                sweep_qubit='AncT', excitations=0)
    AncT.CZ_corr_amp(fix_phase_qcp()[0])
    print_CZ_pars(AncT, DataT)

"""
Bell-state Tomography
"""
MC.soft_avg(1)  # To be removed later, should not be needed
for iii in range(10):
    for target_bell in [0]:
        mq_mod.tomo2Q_bell(bell_state=target_bell, device=S5,
                           qS_name='DataT', qCZ_name='AncT',
                           nr_shots=1024, nr_rep=1)
        tomo.analyse_tomo(MLE=False, target_bell=target_bell % 10)
