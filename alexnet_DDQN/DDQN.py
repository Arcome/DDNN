from Double_DQN_RL import DoubleDQN
import tensorflow as tf
import numpy as np
import copy
import operator
import random
from client_old_scheduler import Client
import  sys
from collections import defaultdict

MEMORY_CAPACITY = 1000
BATCH_SIZE = 32
s_dim = 8
Dsigpower = 0.2
Csigpower = 0.6

def make_layer(inputs, in_size, out_size, activate=None):
    weights = tf.Variable(tf.random_normal([in_size, out_size]))
    basis = tf.Variable(tf.zeros([1, out_size]) + 0.1)
    result = tf.matmul(inputs, weights) + basis
    if activate is None:
        return result
    else:
        return activate(result)

# Desktop LK:  515.6911086859752
# Desktop Jetson:  1789.0332954333326
# Desktop Tao:  529.9081637732563
# Desktop En:   290.28551555314203
# Desktop Xgw:  440.7585252374407

# LK: allocated = -0.29809855407537905 * device_state[0] + 48.51393977760652
# Jet: allocated = -0.18164749165106978 * device_state[0] + 42.586058387463765
# Tao: allocated = -0.498906297535747 * device_state[0] + 64.49022665044114
# En: allocated = -0.2896014602981442 * device_state[0] + 40.76976270155157
# Xgw: allocated = -0.3714268329783997 * device_state[0] + 45.513139641010035
# Server: allocated = 0.013928354122299933 * device_state[0] + 14.242107544873745



def estimate_value(service_demand, input_data, device_state, current_cost, observation, device):
    if device == 's1': # Server
        comden = 132.6083862236326
        maxCPU = 2.5e9
        allocated = 0.01392835 * device_state[0] + 14.24210754
    elif device == 'j1': # Jetson
        comden = 1789.033295433326
        maxCPU = 2e9
        allocated = -0.18164749165106978 * device_state[0] + 42.586058387463765
    elif device == 'd1': # Desktop LK
        comden = 515.6911086859752
        maxCPU = 3.6e9
        allocated = -0.29809855 * device_state[0] + 48.51393978
    elif device == 'e1': # Desktop En
        comden = 290.28551555314203
        maxCPU = 3.4e9
        allocated = -0.28960146 * device_state[0] + 40.7697627
    elif device == 'f1': # Desktop Xgw
        comden = 440.7585252374407
        maxCPU = 3.4e9
        allocated = -0.37142683 * device_state[0] + 45.51313964
    else:  # Desktop oyt
        comden = 529.9081637732563
        maxCPU = 2.4e9
        allocated = -0.4989063 * device_state[0] + 64.49022665
    computing_delay = service_demand * comden / (maxCPU * allocated / 100)
    trans = input_data / (device_state[1]*8e3)
        # D2D trans

    transpower = 0.25
    power_com = trans * transpower

    total = observation[5]*(computing_delay + trans) + observation[6]*power_com

    gain = min(0, total - current_cost) + device_state[3]
    return gain


def pick_device(service_demand, input_data, available_device, record_probed_action, device_state, current_cost, observation):
    count = {}
    ip = {}
    print("avai_device", available_device)
    for i in range(len(available_device)):
        device = available_device[i][0]
        ip[device] = available_device[i][1]
        if record_probed_action[device] != 1:
            count[device] = estimate_value(service_demand, input_data, device_state[device], current_cost, observation, device)

    final = sorted(count.items(), key=operator.itemgetter(1))
    print("final", final)
    device = final[0][0]
    return device, ip[device], final[0][1]


def device_state_update(device, device_state, comp, comm, connec, probing_cost):
    if device in device_state.keys():
        ncomp = (device_state[device][0] * device_state[device][4] + comp)/(device_state[device][4] + 1)
        ncomm = (device_state[device][1] * device_state[device][4] + comm) / (device_state[device][4] + 1)
        nprobing_cost = (device_state[device][3] * device_state[device][4] + probing_cost) / (device_state[device][4] + 1)
        ntimes = device_state[device][4] + 1
        device_state[device] = [ncomp, ncomm, connec, nprobing_cost, ntimes]
    else:
        device_state[device] = [comp, comm, connec, probing_cost, 1]
    return device_state


def device_info():
    service_amount = 128568# 22696 #b
    service_size = 128568 # 22696 #b
    capacity = 0.2
    power = 0.9
    lamda_1 = 1
    lamda_2 = 1
    return service_amount, service_size, capacity, power, lamda_1, lamda_2

def catch_list():
    ip_list = dict({#"192.168.1.128": "r1",
                     "192.168.26.66": "s1",
                     "192.168.1.101": "j1",
                     "192.168.1.199": "d1",
                     "192.168.1.106": "e1",
                     "192.168.1.169": "f1",
                     "192.168.1.150": "k1",
                     # "127.0.0.1": "l1"
                     })
    # ip_list = dict({"192.168.1.199": "d1",
    #                "192.168.26.66": "s1"
    #                })
    # ip_list = [
    #     "192.168.1.128",  # Raspberry
    #     "192.168.26.66",  # Server
    #     "192.168.1.101",  # Jetson
    #     "192.168.1.199",  # Desktop
    #     "127.0.0.1",  # Local
    # ]
    ip = ["192.168.26.66", "192.168.1.101", "192.168.1.199", "192.168.1.150", "192.168.1.169", "192.168.1.106"]
    np.random.shuffle(ip)
    ip_num = len(ip_list)
    newlist = dict({})
    current_ip_num = random.randint(1, ip_num)
    for i in range(0, current_ip_num):
        newlist[ip[i]] = ip_list[ip[i]]
    return newlist

def classification(available_edge_list, lamda_1, lamda_2):
    level_num = 5
    observation = np.zeros(level_num + 2)
    type_device = defaultdict(list)
    record_probed_action = defaultdict(list)
    # categorize the device
    for key in available_edge_list:
        type_device[available_edge_list[key]] = 0
        if available_edge_list[key] == 's1':
            type_device[0].append([available_edge_list[key], key])
            observation[0] += 1
        elif available_edge_list[key] == 'j1':
            type_device[1].append([available_edge_list[key], key])
            observation[1] += 1
        elif available_edge_list[key] == 'd1':
            type_device[2].append([available_edge_list[key], key])
            observation[2] += 1
        elif available_edge_list[key] == 'e1' or available_edge_list[key] == 'f1':
            type_device[3].append([available_edge_list[key], key])
            observation[3] += 1
        else:
            type_device[4].append([available_edge_list[key], key])
            observation[4] += 1
    observation[level_num] = lamda_1
    observation[level_num + 1] = lamda_2

    return observation, type_device, record_probed_action

def receive_prob_info_change(observation, service_amount, service_size, comp, connec, comm, probing_cost, action, u, min_cost, best_device_ip, device_ip, device):
    if device == 's1':
        comden = 132.6083862236326
        maxCPU = 2.5e9
        allocated = 0.01392835 * comp + 14.24210754
    elif device == 'j1':
        comden = 1789.033295433326
        maxCPU = 2e9
        allocated = -0.23811474 * comp + 43.41248101
    elif device == 'd1':
        comden = 515.6911086859752
        maxCPU = 3.6e9
        allocated = -0.29809855 * comp + 48.51393978
    elif device == 'e1':
        comden = 290.28551555314203
        maxCPU = 3.4e9
        allocated = -0.28960146 * comp + 40.7697627
    elif device == 'f1':
        comden = 440.7585252374407
        maxCPU = 3.4e9
        allocated = -0.37142683 * comp + 45.51313964
    else:
        comden = 529.9081637732563
        maxCPU = 2.4e9
        allocated = -0.4989063 * comp + 64.49022665
    computing_delay = service_amount * comden / (maxCPU * allocated / 100)
    print("BPBPBP: current Band: ", comm)
    transmission_delay = service_size / (comm*8e3)  # + output_data / self.Dtrans_rate
    delay = computing_delay + transmission_delay
    power_com = transmission_delay * 0.25
    cost = observation[5] * delay + observation[6] * power_com
    probe_cost = probing_cost
    observation[action] -= 1
    # self.features_space[action + app_k* connection_k] += 1
    print("*******esti comp*********", computing_delay)
    print("*******esti trans********", transmission_delay)
    # print("time", delay)
    # print("power", power_com)
    # print("probe", probing_cost)

    current_cost = u + min(0, cost - min_cost) + probe_cost

    gain = min(0, cost - min_cost) + probe_cost

    min_cost = min(min_cost, cost)
    if min_cost == cost:
        best_device_ip = device_ip
    print("best cost", current_cost)
    # print("mini", min_cost)
    # print("===================================================")
    return observation, -gain, best_device_ip, current_cost, min_cost, cost



def main():
    client = Client()
    # the table of device state, i.e., id, time-average computing capacity, transmission rate, communication type, probing cost, probed times, (recent probed time)
    device_state = {}
        # action sequencing
    RL = DoubleDQN(6, 10,
                   learning_rate=0.01,
                   reward_decay=0.8,
                   e_greedy=0.9,
                   replace_target_iter=100,
                   memory_size=1000,
                   batch_size=32
                   )

    step = 0
    step_ep = 0
    f1 = open('resultData/HRL_result.txt', 'w')
    f2 = open('resultData/HRL_stage.txt', 'w')
    f3 = open('resultData/HRL_error.txt', 'w')
    for episode in range(1000):

        service_amount, service_size, capacity, power, lamda_1, lamda_2 = device_info()

        current_cost = lamda_1 * service_amount/capacity + lamda_2 * power * service_amount

        available_edge_list = catch_list()

        device_number = len(available_edge_list)
        min_cost = current_cost
        observation, type_device, record_probed_action = classification(available_edge_list, lamda_1, lamda_2)
        best_device_ip = "local"
        done = False
        prob = np.zeros(device_number + 1)
        total_cost = np.ones(device_number + 1)
        total_cost = list(total_cost * float('inf'))
        total_cost[0] = current_cost
        print("====================================")
        print("episode:", episode)
        print("observ", observation)
        stage = 0
        while True:
            # RL choose action based on observation
            observation1 = np.append(observation, current_cost)
            observation1 = np.append(observation1, min_cost)
            observation1 = np.append(observation1, stage)
            # print(observation1)
            action = RL.choose_action(observation1, stage)
            if action == env.n_actions:
                print("type", action)
                # print(current_cost)
                # print("ob_", observation1_)
                RL.store_transition(observation1, action, 0, observation1)
                done = True
            else:
                explore = False
                for i in range(len(type_device[action])):
                    if type_device[action][i][0] not in device_state.keys():
                        device = type_device[action][i][0]
                        device_ip = type_device[action][i][1]
                        explore = True

                if not explore:
                    if np.random.uniform() < 0.9:
                        device, device_ip, esti_gain = pick_device(service_amount, service_size, type_device[action],
                                                                   record_probed_action, device_state, min_cost,
                                                                   observation)
                    else:
                        tuple = random.sample(type_device[action], 1)[0]
                        device = tuple[0]
                        device_ip = tuple[1]
                        esti_gain = estimate_value(service_amount, service_size, device_state[device], current_cost,
                                                   observation, device)

                print("device", device)
                record_probed_action[device] = 1

                comp, connec, comm, probing_cost = client.probing(device_ip)
                probing_cost = probing_cost * (1 + 0.165)
                comp += 0.1
                print("===================")
                print("info", comp, connec, comm, probing_cost)
                observation_, reward, best_device_ip, current_cost, min_cost, sum_cost = receive_prob_info_change(
                    observation, service_amount, service_size, comp, connec, comm,
                    probing_cost, action, current_cost, min_cost, best_device_ip, device_ip, device)

                device_state = device_state_update(device, device_state, comp, comm, connec, probing_cost)
                stage += 1
                prob[stage] = probing_cost + prob[stage - 1]
                observation1_ = np.append(observation_, current_cost)
                observation1_ = np.append(observation1_, min_cost)
                observation1_ = np.append(observation1_, stage)
                RL.store_transition(observation1, action, reward, observation1_)

                if (step > 20) and step % 5 == 0:
                    RL.learn()

                # swap observation
                observation = copy.deepcopy(observation_)
                steptime += 1

            # break while loop when end of this episode
            if done or stage == device_number:
                print("current cost", current_cost)
                print("stage", stage)
                f1.write(str(current_cost) + '\r\n')
                f2.write(str(stage) + '\r\n')
                if best_device_ip == "local":
                    print("local execution")
                else:
                    transfer_latency, computing_latency = client.transfer(best_device_ip)
                    cost = computing_latency + transfer_latency + 0.25 * transfer_latency + prob[stage]
                    f1.write(str(cost) + '\r\n')
                    estimated_error = (current_cost - cost) / current_cost
                    # print("estimated error", (current_cost - cost)/current_cost)
                    print("estimated error", estimated_error)
                    f3.write(str(estimated_error) + '\n')
                # f1.flush()
                break
            step += 1


        step_ep += 1
        # threshold estimator update after a whole episode
        if (step_ep > 20) and (step_ep % 5 == 0):
            var *= 0.90  # decay the action randomness
            bp.train()
    f1.close()
    f2.close()
    f3.close()

if __name__ == '__main__':
    main()
