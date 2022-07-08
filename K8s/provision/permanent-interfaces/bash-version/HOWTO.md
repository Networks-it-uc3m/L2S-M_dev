Modify the root crontab:
```bash
sudo crontab -e
```

Add the following line at the end:
````nano
@reboot sh /home/[change-to-user]/L2S-M/K8s/provision/test-vxlan-reboot.bash [interface-to-use-in-vxlan] /home/[change-to-user]/L2S-M/K8s/provision/vxlans.txt
