# 思构手记

个人技术主页独立项目，正式域名为 `https://linhengyi.xyz/`。

当前阶段：网站已上线，HTTPS 与浏览器验证通过；公安备案草稿待负责人身份认证与提交前确认。

- [需求规格](docs/requirements.md)
- [技术方案](docs/technical-plan.md)
- [访问问题排查记录](docs/diagnosis-20261028.md)
- [公开内容依据](docs/content-sources.md)
- [发布与维护记录](docs/deployment-20261028.md)
- [实现验证记录](docs/implementation-20261028.md)
- [备案信息准备](docs/filing-preparation.md)

## 本地查看

页面位于 `public/`，由 HTML、CSS 和 SVG 组成，无需安装依赖或构建。

```powershell
python -m http.server 4173 --bind 127.0.0.1 --directory public
```

打开 `http://127.0.0.1:4173/`。预览服务器只用于本地查看；正式部署只发布 `public/`。

## 部署接入

部署目标：现有阿里云服务器的 Caddy 入口。接入文件位于 `deploy/`；在服务器最新配置核验、备份和配置校验通过后使用。

- `/opt/sigou-notes/site/public`：当前版本的公开文件。
- `/opt/sigou-notes/deploy/site.caddy`：独立站点配置。
- `compose.sigou-notes.yaml`：给现有 `edge` 追加只读目录挂载。
- 现有 Caddy 主配置需追加 `import /etc/caddy/sigou-notes.caddy`，日常 Compose 管理命令需保留本项目覆盖文件。
- 主域名 A 记录指向实际服务器；www 的 CNAME 指向主域名。

实际变更与验证结果记录在交付文档中；网站上线后再准备公安备案重新提交。

部署脚本 `scripts/deploy_site.py` 用于本次首次安装，分别执行准备、启用和恢复原入口。脚本比较现有全部服务配置，只允许为 `edge` 新增两个指定只读挂载，并核对其他容器 ID 保持一致。运行保护规则测试：

```powershell
python -m unittest discover -s tests -v
```

用户于 2026-10-28 确认：上线与“思构手记”一致的个人技术主页，展示网站介绍和真实项目说明；补齐备案访问地址、核对 IP 和网站分类，重新提交前人工确认。随后明确要求新建独立项目。
