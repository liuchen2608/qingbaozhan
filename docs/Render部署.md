# 在 Render 打开完整应用

仓库包含可部署的 `render.yaml`。这不是已经上线的证明；必须在你的Render账号创建服务并拿到实际地址后，才能验证外网访问。

## 一次性连接

1. 登录你自己的Render控制台，选择 **New → Blueprint**。
2. 连接GitHub，选择 `liuchen2608/qingbaozhan`，分支 `main`。若列表没有仓库，在GitHub授权界面为Render增加该仓库的访问权。
3. Render读取仓库根目录的render.yaml。填写 `HUB_USERNAME` 和 `HUB_PASSWORD`，密码至少16字符；这些值在Render填写，不提交GitHub、不发到聊天。
4. **先核对费用再创建**：此配置采用Starter服务和1GB持久磁盘，属于付费部署，以Render当时页面报价为准。不要在未接受费用时点击最终部署。持久磁盘用于保留SQLite知识库；免费实例的临时文件系统不适合长期保存个人数据。
5. 确认部署后等待状态变成Live。打开服务页面中Render实际生成的HTTPS地址，使用刚才设置的用户名密码登录。

若只想免费验证页面，请先说明预算要求；不要直接移除磁盘却以为数据能长期保留。可改为临时演示部署，但重启、休眠或重新部署后数据可能丢失。

## 验证与模型

把服务实际生成的URL发到当前对话，我会从外部检查响应。不需要把登录密码发给我：未登录应返回401并弹出浏览器登录框；`/healthz`应返回200。你登录后确认能录入、检索并导出，再配置模型。

服务Environment中按.env.example添加MODEL_PROVIDER、MODEL_BASE_URL、MODEL_ID、MODEL_API_KEY，保存后重启服务。无模型配置时可以先测试数据管理和人工分析。

所有页面、静态资源、API、导入导出和API文档都受登录保护，只有无数据的健康检查公开。Render自动提供RENDER_EXTERNAL_HOSTNAME以允许平台分配的域名；自定义域名需将其加入HUB_ALLOWED_HOSTS，多个域名用英文逗号分隔，不含协议或路径。

不要横向扩展为多个实例，本版使用单实例SQLite。磁盘不是备份，仍应定期安全备份数据库；Markdown/Excel导出不含分析历史。HTTP Basic登录适合个人单用户HTTPS部署，浏览器会缓存登录状态；公共电脑使用独立隐私窗口并在完成后关闭。没有多用户、账号恢复或登录防爆破系统。
