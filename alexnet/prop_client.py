import socket
import threading
import time
import hashlib
import struct
import datetime
import os
import numpy as np
import tensorflow as tf
from apscheduler.schedulers.blocking import BlockingScheduler

BUFFER_SIZE = 1200
HEAD_STRUCT = '128sIqi32xs'
info_size = struct.calcsize(HEAD_STRUCT)

###################
# FileProcessor: 
# Functions to deal with files
###################
class FileProcessor():
    def cal_md5(self, file_path):
        with open(file_path, 'rb') as fr:
            md5 = hashlib.md5()
            md5.update(fr.read())
            md5 = md5.hexdigest()
            return md5

    def get_file_info(self, file_path):
        # file_name = os.path.basename(file_path)
        # file_name_len = len(file_name)
        file_size = os.path.getsize(file_path)
        md5 = self.cal_md5(file_path)
        return file_size, bytes(md5.encode('utf-8'))

###################
# SendScheduler: 
# Schedule send jobs with multi-thread. The file is pieced already before input. In
#  SendScheduler, one second sends one file so as to accurately control the 
#  bandwidth (kB/s). Note that it uses the thread termination to shutdown the send 
#  schedule.
###################
class SendScheduler(threading.Thread):
    def __init__(self):
        self._running = True
        self.scheduler = BlockingScheduler()
            
    def send_job(self, sock, send_file, times):
        print("[{}kB/s] Client: sending file packet {}...".format(len(send_file),times))
        sock.send(send_file)
        # print(len(send_file))
        sock.recv(10)

    def run(self, sock, send_files):
        i = 0
        for send_file in send_files:
            self.scheduler.add_job(func=self.send_job, args=(sock, send_file, i, ), 
                next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=i))
            i += 1
        try:
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.scheduler.shutdown()

    def terminate(self):
        self.scheduler.shutdown()
        print("Client: Send scheduler terminated")
        self._running = False
    

###################
# Client: 
# The client. See notes on each function.
###################        
class Client(threading.Thread):
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        with open("sprintGo.txt","r") as ulFile:
            self.size_arrange = list(int(float(ul)/8) for ul in ulFile.readlines())
            ulFile.close()
        self.required_index = 0
        
        # Assume all agree the port: 50000
        self.port = 50000
        self.ip_list = [
            "192.168.1.128", # Raspberry
            "192.168.26.66" # Server
            "192.168.1.101", # Jetson
            "192.168.1.199", # Desktop
            "127.0.0.1", # Local
        ]
        
    ## The ip selection model
    def select_ip(self, ip_info, rtt):
        cpu_percent, conn_type = struct.unpack(HEAD_STRUCT,ip_info)
        current_band = self.size_arrange[self.required_index]
        #
        #*********************Add your model here**************************
        #                          YOUR MODEL
        #******************************************************************
        #
        isProp = True
        return isProp

    ## Porping each ip in ip_list
    def proping(self, ip_list):
        isProp = True
        for ip in ip_list:
            if isProp:
                self.check_conn(ip, self.port)

                proping_time0 = time.time()
                self.sock.send(b"Resource query")
                ip_info = self.sock.recv(BUFFER_SIZE)
                proping_time1 = time.time()
                rtt = proping_time1 - proping_time0
                isProp = self.select_ip(ip_info, rtt)
                if not isProp:
                  target_ip = ip            
                  break
        return target_ip

    ## Run the client
    def run(self, ip, port):
        print("Client: Here is the client side")

        #*********************Proping Processs********************
        # target_ip = self.proping(self.ip_list)
        target_ip = "127.0.0.1"

        #*********************Transferring Process*******************     
        self.transfer(target_ip, self.port)

    ## Check the connection
    def check_conn(self, ip, port):
        # # Check the connection
        print("Client: Connecting %s:%s..." % (ip, port))
        try:
            self.sock.connect((ip, port))            
            print("Server: Connection Succeed")
        except Exception as e:
            print("Server: Connection ERROR")
            print("Exception: ", repr(e))
            exit()
        # Check the file to transfer
        isReady = self.sock.recv(BUFFER_SIZE)
        # self.sock.send(b"Client: Ready")
        if isReady.decode() == "Server: Ready":
            print(isReady)
            return True
        else:
            print("Connection fail")
            return False

    ## Transfer the files
    def transfer(self, ip, port):
        isReady = self.check_conn(ip, port)
        if not isReady:
            return
        self.sock.send(b"File transfer")
        
        image_path = "./testImages/"
        image_list = list(image_name for image_name in os.listdir(image_path))
        image_num = len(image_list)
        
        print("File num: ", image_num.to_bytes(4, byteorder='big'),"/",len(image_list))
        self.sock.send(image_num.to_bytes(4, byteorder='big'))
        # print("MIN:", min(self.size_arrange)) 106.84311625
        # print("MAX:", max(self.size_arrange)) 1183.70575

        # For each image, first send the file info. Then cut one file into file pieces
        # in send_files, which will then be input to the send scheduler to transfer 
        # according to the bandwidth dataset
        for image_name in image_list:
            file_processor = FileProcessor()
            file_size, md5 = file_processor.get_file_info(image_path+image_name)
            file_info = struct.pack(HEAD_STRUCT, bytes(image_name.encode('utf-8')),
                len(image_name), file_size, self.required_index ,md5)
            self.sock.send(file_info)
            receive_packet = self.sock.recv(BUFFER_SIZE)
            print(receive_packet)
            sent_size = 0

            # Cut the file to pieces
            with open(image_path+image_name, 'rb') as img:
                send_files = []
                while sent_size < file_size:
                    remained_size = file_size - sent_size
                    require_size = self.size_arrange[self.required_index]
                    self.required_index += 1
                    send_size = min(require_size, remained_size)
                    send_files.append(img.read(send_size))
                    sent_size += send_size
                    # print(send_size)
                img.close()
            
            # Run the send scheduler
            print("Client: sending image {}...".format(image_name))
            send_scheduler = SendScheduler()
            send_thread = threading.Thread(target=send_scheduler.run, args=(self.sock,send_files,))
            send_thread.start()
            time.sleep(len(send_files))
            send_scheduler.terminate()
            print("Client: Send finished")

            reply_packet = self.sock.recv(2)
            if reply_packet == b"OK":
                continue
            else:
                print("Connection ERROR.\nCurrent file:",image_name)
                break

        # Receive the result from the server
        for i in range(image_num):
            imgName = self.sock.recv(BUFFER_SIZE)
            self.sock.send(b"OK")
            result = self.sock.recv(BUFFER_SIZE)
            print("{}: {}\n----".format(imgName,result))
        
        self.sock.close()


if __name__ == '__main__':
    print("Client: Test start...")
    ip = "127.0.0.1" # Local
    port = 50000
    client = Client()
    client.run(ip, port)