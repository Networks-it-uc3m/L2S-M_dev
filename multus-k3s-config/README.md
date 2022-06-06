#K3s Installation
Apply the multus descriptor with the following script

kubectl create -f ./multus-daemonset.yml 

Install the host-device plugin:

sudo apt update
sudo apt install golang-go
git clone https://github.com/containernetworking/plugins.git
cd  $HOME/plugins/plugins/main/host-device
sudo go build -o "/var/lib/rancher/k3s/data/current/bin" ./host-device.go
