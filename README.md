## 

a cluster should be available under the project, e.g.
-    g1-small => not enough resources
-    e2-standard-8 => too-much 
-    e2-standard-4 => too-much 
-    e2-standard-2 => ?

gcloud container clusters create gc-tricot --region=europe-west1 --machine-type=e2-standard-2 --num-nodes 1
run the command to connect to the cluster

if gcloud is slowwww:
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=1
sudo sysctl -w net.ipv6.conf.default.disable_ipv6=1

sa_path = root_path / 'thematic-grove-252706-d9129189f4b3.json'
project_id = "thematic-grove-252706"
region = "europe-west1"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa_path)
