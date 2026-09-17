# 发布到 GitHub

## 公开前检查

1. 确认根目录 `LICENSE`，核对代码、素材和第三方组件的公开权限。
2. 检查 `.gitignore`，不要提交 `data/`、`.env`、权重、数据库、日志或虚拟环境。
3. 检查 `git status --short` 和 `git diff --cached`；忽略规则不会移除已跟踪文件或旧提交。
4. 审查历史中的敏感信息与提交邮箱。发现秘密应先轮换，再清理历史或从干净目录发布新仓库；不要直接公开未经审核的历史。
5. 完成贡献指南中的测试，不将本机验证描述为生产安全审计。

## 最简流程（已有本地 Git 仓库）

在 GitHub 创建**空仓库**，不勾选生成 README、LICENSE 或 `.gitignore`，在本项目根目录执行：

```powershell
# 仅未配置身份时需要，可使用 GitHub noreply 邮箱
git config user.name "你的名字"
git config user.email "你的提交邮箱"
git add .
git diff --cached --stat
git commit -m "Prepare public release"
git branch -M main
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

已存在 `origin` 时先检查，再使用 `git remote set-url origin <正确地址>`。HTTPS 推送按 Git Credential Manager 提示登录，不把令牌写进 URL。无需再次 `git init`，无需强制推送。

后续：`git add .` → `git commit -m "说明"` → `git push`。

建议先创建 Private 仓库，确认许可证与历史后转为 Public；填写简介和 Topics、启用私密漏洞报告、保护主分支，并通过 Tag / Release 说明版本边界。
