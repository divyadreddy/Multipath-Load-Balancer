import random
from collections import defaultdict
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import set_ev_cls
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ipv6
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import arp
from ryu.lib.packet import ipv4
from ryu.lib import mac, ip
from ryu.topology import event


class MultiPathLoadBalancer(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    
    def __init__(self, *args, **kwargs):
        super(MultiPathLoadBalancer, self).__init__(*args, **kwargs)
        self.switches = []
        self.hosts = {}
        self.datapaths = {}
        self.arp_table = {}
        self.multipath_groupids = {}
        self.groupids = []
        self.adjMap = defaultdict(dict)
        self.port_bw = defaultdict(lambda: defaultdict(lambda: 10000000))
        self.sequence = 0 

    def shortest4Paths(self, src, dst):
        if src == dst:
            # host target is on the same switch
            return [[src]]
        paths = []
        stack = [(src, [src])]
        while stack:
            (node, path) = stack.pop()
            for next in set(self.adjMap[node].keys()) - set(path):
                if next is dst:
                    paths.append(path + [next])
                else:
                    stack.append((next, path + [next]))
        print("All the paths", src, "to", dst, " : ", paths)
        paths_costs = []
        for path in paths:
            path_cost = 0
            for i in range(len(path) - 1):
                s = path[i]
                d = path[i+1]
                curr_bw = min(self.port_bw[s][self.adjMap[s][d]], self.port_bw[d][self.adjMap[d][s]])
                path_cost += 10000000/curr_bw
            paths_costs.append([path_cost, path])
        paths_costs = sorted(paths_costs, key=lambda x: x[0])[0:min(len(paths), 4)]
        print("best paths :", paths_costs)
        return paths_costs


    def addPaths(self, src, src_port, dst, dst_port, ip_src, ip_dst):
        paths_costs = self.shortest4Paths(src, dst)
        path_cost = []
        paths = []
        for cost, path in paths_costs:
            path_cost.append(cost)
            paths.append(path)
        sumPathsCost = sum(path_cost)
        
        paths_with_ports = []
        for path in paths:
            p = {}
            input_port = src_port
#            for s1, s2 in zip(path[:-1], path[1:]):
            for i in range(1, len(path)):
                s1 = path[i-1]
                s2 = path[i]
                output_port = self.adjMap[s1][s2]
                p[s1] = (input_port, output_port)
                input_port = self.adjMap[s2][s1]
            p[path[-1]] = (input_port, dst_port)
            paths_with_ports.append(p)
        
        switches_in_paths = set().union(*paths)
        for switch in switches_in_paths:
            dp = self.datapaths[switch]
            ofp = dp.ofproto
            ofp_parser = dp.ofproto_parser
            ports = defaultdict(list)
            actions = []
            i = 0
            for path in paths_with_ports:
                if switch in path:
                    input_port = path[switch][0]
                    output_port = path[switch][1]
                    if (output_port, path_cost[i]) not in ports[input_port]:
                        ports[input_port].append((output_port, path_cost[i]))
                i += 1
            for input_port in ports:
                ip_match = ofp_parser.OFPMatch(eth_type=0x0800, ipv4_src=ip_src, ipv4_dst=ip_dst)
                arp_match = ofp_parser.OFPMatch(eth_type=0x0806, arp_spa=ip_src, arp_tpa=ip_dst)
                out_ports = ports[input_port]
                print("output ports", out_ports)
                actions = None
                if len(out_ports) > 1:
                    new_group = False
                    group_id = None
                    if (switch, src, dst) not in self.multipath_groupids:
                        new_group = True
                        group_id = random.randint(0, 1000)
                        while group_id in self.groupids:
                            group_id = random.randint(0, 1000)
                        self.multipath_groupids[switch, src, dst] = group_id
                        self.groupids.append(group_id)
                    group_id = self.multipath_groupids[switch, src, dst]

                    buckets = []
                    for port, weight in out_ports:
                        print("weight", weight)
                        bucket_weight = int(round(100 - 100*weight/sumPathsCost))
                        bucket_action = [ofp_parser.OFPActionOutput(port)]
                        buckets.append(ofp_parser.OFPBucket(weight=bucket_weight, watch_port=port, watch_group=ofp.OFPG_ANY, actions=bucket_action))
                    flag = ofp.OFPGC_MODIFY
                    if new_group:
                        flag = ofp.OFPGC_ADD
                    msg = ofp_parser.OFPGroupMod(dp, flag, ofp.OFPGT_SELECT, group_id, buckets)
                    dp.send_msg(msg)
                    actions = [ofp_parser.OFPActionGroup(group_id)]
                elif len(out_ports) == 1:
                    actions = [ofp_parser.OFPActionOutput(out_ports[0][0])]
                if actions:
                    self.addFlowToSwitch(dp, 5000, ip_match, actions)
                    self.addFlowToSwitch(dp, 1, arp_match, actions)
        src_output_port = paths_with_ports[0][src][1]
        return src_output_port

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switchFeatures(self, event):
        print("info : switch features")
        datapath = event.msg.datapath
        ofp= datapath.ofproto
        ofp_parser= datapath.ofproto_parser
        match = ofp_parser.OFPMatch()
        actions = [ofp_parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self.addFlowToSwitch(datapath, 0, match, actions)

    def addFlowToSwitch(self, dp, priority, match, actions):
        ofp_parser = dp.ofproto_parser
        instructions = [ofp_parser.OFPInstructionActions(dp.ofproto.OFPIT_APPLY_ACTIONS, actions)]
        msg = ofp_parser.OFPFlowMod(datapath=dp, priority=priority, match=match, instructions=instructions)
        dp.send_msg(msg)
        
    @set_ev_cls(event.EventSwitchEnter)
    def switchAdd(self, event):
        print("info : switch enter")
        # print(event.switch.dp.__dict__)
        switch_dp = event.switch.dp
        switch_id = switch_dp.id
        ofp_parser = switch_dp.ofproto_parser
        if switch_dp.id not in self.switches:
            req = ofp_parser.OFPPortDescStatsRequest(switch_dp) # for getting bandwidth
            switch_dp.send_msg(req)
            self.datapaths[switch_id] = switch_dp
            self.switches.append(switch_id)
                       
    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_stats_reply_handler(self, event): # for getting bandwidth
        print("info : stats reply")
        switch_id = event.msg.datapath.id
        for port_info in event.msg.body:
            self.port_bw[switch_id][port_info.port_no] = port_info.curr_speed
            
    @set_ev_cls(event.EventLinkAdd, MAIN_DISPATCHER)
    def linkAdd(self, event):
        print("info : add link")
        src = event.link.src
        dst = event.link.dst
        self.adjMap[src.dpid][dst.dpid] = src.port_no
        self.adjMap[dst.dpid][src.dpid] = dst.port_no
    
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packetIn(self, event):
        # print("info : packet enter")
        msg = event.msg
        input_port = msg.match['in_port']
        datapath = msg.datapath
        switch_id = datapath.id
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth.ethertype == 35020:
            return
        src = eth.src
        dst = eth.dst
 
        arp_ = pkt.get_protocol(arp.arp)
        ofp_parser= datapath.ofproto_parser
        ofp= datapath.ofproto
        output_port = ofp.OFPP_FLOOD
        if pkt.get_protocol(ipv6.ipv6):  # Drop the IPV6 Packets.
            match = ofp_parser.OFPMatch(eth_type=eth.ethertype)
            self.addFlowToSwitch(datapath, 1, match, [])
            return

        if src not in self.hosts:
            self.hosts[src] = [switch_id, input_port]

        if arp_:
            print("info : arp_ enter", switch_id, pkt)
            src_ip = arp_.src_ip
            dst_ip = arp_.dst_ip
            # print("\nsequence", self.sequence)
            h2 = None
            if arp_.opcode == arp.ARP_REQUEST and dst_ip in self.arp_table:
                # self.sequence += 1
                self.arp_table[src_ip] = src
                h2 = self.hosts[self.arp_table[dst_ip]]
            elif(arp_.opcode == arp.ARP_REPLY):
                self.arp_table[src_ip] = src
                h2 = self.hosts[dst]
                # self.sequence +=2
            # print("after", self.sequence, "\n")
            if h2:
                h1 = self.hosts[src]
                output_port = self.addPaths(h1[0], h1[1], h2[0], h2[1], src_ip, dst_ip)
                self.addPaths(h2[0], h2[1], h1[0], h1[1], dst_ip, src_ip) # reverse
        
        actions = [ofp_parser.OFPActionOutput(output_port)]
        msg_ = None
        if msg.buffer_id == ofp.OFP_NO_BUFFER:
            msg_ = ofp_parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=input_port, actions=actions, data=msg.data)
        else:
        	msg_ = ofp_parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id, in_port=input_port, actions=actions, data=None)
        datapath.send_msg(msg_)

