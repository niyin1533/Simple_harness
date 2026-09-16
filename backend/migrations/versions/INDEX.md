<!-- FORMAT-DOC: Update when files in this folder change -->

# backend/migrations/versions

本目录职责：冻结的初始表结构；将长内容字段升级为 LONGTEXT等，文件职责如下。

## Files

| File | Role | Responsibilities |
|---|---|---|
| 0001_baseline.py | Migration | 冻结的初始表结构 |
| 0002_large_text.py | Migration | 将长内容字段升级为 LONGTEXT |
| 0003_memory_metadata.py | Migration | 为记忆添加可空治理元数据，保留全部旧数据 |
