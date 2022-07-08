## Install

Inside this folder, perfom the following commands:

```bash
sudo cp veth/25* /etc/systemd/network
sudo cp 99-l2sm.yaml /etc/netplan/
```

Apply the changes and check that the interfaces were succesfully created:
```bash
sudo netplan apply

```


For the vxlan, (and now temporarily veth) since netplan does not support (yet) vxlan interfaces, we will use a cronjob (for now). Modify the script with the tunnels to be created:

Apply the changes and check that the vxlans were succesfully created:
```bash
sudo bash ./L2S-M/K8s/provision/permanent-interfaces/vxlan/test-vxlan-reboot.bash [interface_to_use]
```

Modify the crontab with the following command:
````bash
sudo crontab -e
```

Add the following line:
````nano
@reboot bash [PATH-TO-FILE]`/test-vxlan-reboot.bash [interface_to_use]
```
