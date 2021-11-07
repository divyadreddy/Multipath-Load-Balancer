# Execution Steps 
### Instructions to setup environment
1. Requirement - Ubuntu 
2. VirualBox having Ubuntu
    `sudo apt install virtualbox`
    - Download the latest iso image for Ubuntu (20.04). Use this image in virtual box creation
    - Make sure you are alloting atleast 10 GB of space, 2 GB of RAM for functioning
3. Mininet
    `sudo apt-get update`
     `sudo apt-get upgrade -a`
     `sudo apt-get dist-upgrade -a`
     `sudo apt-get install git`
     `git clone git://github.com/mininet/mininet`
     `mininet/util/install.sh -a`
4. Ryu
    `pip install ryu`
### Instructions to run
1. Open the terminal in the folder where you have multipath_loadbalancer.py and topo_3h_5s.py files.
2. Running Ryu Controller
    - Open a terminal and type the following command 
        `ryu-manager --observe-links multipath_loadbalancer.py`
    - This will start the controller at 127.0.0.1:6633
    - Keep this terminal open, you can see how packets are transmitted and different events being executed
3. Mininet
    - Open a terminal and type the following command  
     `sudo python topo_3h_5s.py`
    - This will create the vitual topology and start mininet shell
    - In the mininet shell type `pingall` command, you should get 0% packet drop
    - In the mininet shell type `xterm h1 h2` command, this will open host1 and host2 terminals
    - Type `iperf -s` in host1 to start the server
    - Type `iperf -c 10.0.0.1 -P 5` in host2 to start 5 parallel clients and connect to server.
    - We are using multiple clients to see that loadbalancing is happenning
    - Now in a seperate terminal type `sudo ovs-ofctl -O OpenFlow13 dump-ports s1` to see how the number of packets in tx and rx are distributed to different ports, you can replace s1 with any other switch, to see load balancing at that switch.

