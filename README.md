# astrbot_plugin_rollpig_plus

基于 [nonebot-plugin-rollpig-plus](https://github.com/Felis2026/nonebot-plugin-rollpig-plus) 移植的 AstrBot 今日小猪插件。

## 功能（阶段 1）

- **今日小猪** / 今天是什么小猪：每天抽取一只属于你的小猪，生成卡片（头像+名称+描述+性格解析）
- **我的猪圈**：查看解锁数量、收藏率、最高 EX Lv.、本命猪等统计

每个用户每天只抽取一次；重复查看不改变结果；重复抽取会提升 EX Lv. 并累计保底权重。

## 指令

| 指令 | 说明 |
|---|---|
| `今日小猪` / `今天是什么小猪` | 抽取今天的小猪 |
| `我的猪圈` | 查看猪圈统计 |

## 安装

```bash
cd /AstrBot/data/plugins
git clone https://github.com/sfw2099/astrbot_plugin_rollpig_plus
# 重启 AstrBot
```

## 配置

| 配置项 | 默认 | 说明 |
|---|---|---|
| `roast_cooldown_hours` | 8 | 烤猪冷却时间(小时) |
| `roast_charge_max` | 2 | 烤猪最大储存次数 |
| `resource_sync_enabled` | false | 启用云端资源同步 |

## 资源

`resource/` 目录包含 165 只小猪数据（`pig.json`）与图片（`image/`），随插件分发。支持自定义添加：在 `pig.json` 添加对象并将对应图片放入 `image/`（按 id 命名）。

## 许可证

MIT License
