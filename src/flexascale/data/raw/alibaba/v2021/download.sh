#!/bin/bash  
  
BASE="http://aliopentrace.oss-cn-beijing.aliyuncs.com/v2021MicroservicesTraces"
mkdir -p data/MSResource data/MSRTQps

wget -c "$BASE/MSResource/MSResource_0.tar.gz" -P data/MSResource/
wget -c "$BASE/MSRTQps/MSRTQps_0.tar.gz" -P data/MSRTQps/

tar -xzf data/MSResource/MSResource_0.tar.gz -C data/MSResource/
tar -xzf data/MSRTQps/MSRTQps_0.tar.gz -C data/MSRTQps/
