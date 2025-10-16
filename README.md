一个将 Klipper 3D 打印机状态实时同步到企业微信的工具。

本项目需使用公网。

起迪QiDi打印机，通过QiDiLink，可实现无需内网穿透对打印机进行操作。

其他牌子打印机，因为我没有，实现不了


## 配置方法：
### 企业微信应用配置
    注册企业微信并创建自建应用
    在应用设置中启用"API接收消息"
    获取 Token 和 EncodingAESKey（点击随机获取）
    设置接收消息URL为：你的域名/hook_path
    修改 config.conf文件中的 token 和 encoding_aes_key
    运行 Klipper_app.py
    配置企业可信IP
### config.conf 配置文件设置
     [made]修改如下：
     打印机品牌选择：1=起迪，2=其他品牌
     name = 1
     起迪打印机必填项：
     username = your_username
     password = your_password
     IP地址格式：
     起迪打印机：192.168.0.1
     其他：192.168.0.1:7890
     [wechat] 修改如下：
     corp_id企业微信企业ID（路径：我的企业->企业信息->企业ID）
     corp_secret自建应用密钥（路径：应用->自建应用->Secret）
     agent_id自建应用ID（路径：应用->自建应用->AgentId）
### 运行
   Klipper_app.py（必须运行）
   
   Klipper_monitor.py（对打印机状态进行监控，开始 异常 完成，推送消息，可不运行）
   
   pip install -r requirements.txt && python Klipper_app.py runserver 
   
   pip install -r requirements.txt && python Klipper_monitor.py runserver 
## 使用方法：
   直接回复 打印状态、打印进度、拍照、关灯、开灯、系统状态


