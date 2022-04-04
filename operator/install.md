# L2S-M Installation Guide
This guide details the necessary prerequisites to install the L2S-M Kubernetes operator to create and manage virtual networks in your Kubernetes cluster!


# Prerequisites

1. In order to start with the installation of L2S-M, it is necessary to set up the IP tunnel overlay between the nodes that you want to interconnect. In this case, this repository contains an script to generate up to 10 VxLANs, although any IP tunnelling mechanism can be suitable to be used. To use the script, execute the following command in every of the nodes of your cluster:

```bash
sudo ./generate_vxlans.bash
```

If you want to create the VxLANs manually, you can use the following code instead for every VxLAN:

```bash
sudo ip link add [vxlan_Name] type vxlan id [id] dev [interface_to_use] dstport [dst_port]
```

To configure the VXLAN tunnels, you can use the following command for every pair of interfaces you want to configure in their respective nodes:

```bash
sudo bridge fdb append to 00:00:00:00:00:00 dst [dst_IP] dev [vxlan_Name]
```

**WARNING:**  Make sure that the VXLAN id coincides between each tunnel pairs, specially when using the configure_vxlan file. You can use the following table in order to check the associated ids with each one of the vxlans.

| **VXLAN Name** |**ID**  |
|--|--|
| vxlan1 | 1961 |
| vxlan2 |  1962 |
| vxlan3 |  1963 |
| vxlan4 |  1964|
| vxlan5 |  1965 |
| vxlan6 |  1966|
| vxlan7 |  1967|
| vxlan8 |  1968|
| vxlan9 |  1969|
| vxlan10 |  1970|

2. Create the vEth virtual interfaces in every host of the cluster by using the following script
```bash
sudo $HOME/L2S-M/operator/deploy/interfaces/configure_interfaces.bash
```
3. Install the Multus CNI Plugin in your K8s cluster

## Install L2S-M

1. Create the virtual interface definitions using the following command:
 ```bash
kubectl create -f $HOME/L2S-M/K8s/interface_definitions
```
**NOTE:** If you are using interfaces whose definitions are not present in the virtual interfaces definitions in the folder, you must create the corresponding virtual definition in the same fashion as the VXLANs. For example, if you want to use a VPN interface called "tun0", first write the descriptor "tun0.yaml":
 ```yaml
apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
name: tun0
spec:
config: '{
"cniVersion": "0.3.0",
"type": "host-device",
"device": "tun0"
}'
```
Afterwards, apply the new interface definitions using kubectl:
  ```bash
kubectl create -f tun0.yaml
```
2. Create the Kubernetes account Service Account and apply their configuration by applying the following command:
 ```bash
kubectl create -f $HOME/L2S-M/operator/deploy/config/
```

3. Create the Kubernetes Persistent Volume by using the following kubectl command:
 ```bash
kubectl create -f $HOME/L2S-M/operator/deploy/config/
```

4. After the previous preparation, you can deploy the operator in your cluster using the YAML deployment file:
 ```bash
kubectl create -f $HOME/L2S-M/operator/deployOperator.yaml
```

 You can check that the deployment was successful if the pod enters the "running" state using the *kubectl get pods* command.

5. Deploy the virtual OVS Daemonset using the following .yaml:
```bash
kubectl create -f $HOME/L2S-M/operator/daemonset
```
**NOTE:** If you have introduced new interfaces in your cluster besides the vxlans, modify the descriptor to introduce those as well. (Modify both MULTUS annotations and the commands to attach the interface to the OVS switch). 

You are all set!
