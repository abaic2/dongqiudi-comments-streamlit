# 懂球帝评论爬虫 · Streamlit 演示

一个用于抓取并可视化**懂球帝**（dongqiudi.com）新闻 / 战报评论的 Streamlit 应用。

## 功能

- **像懂球帝一样的新闻列表界面**：点「🔄 加载 / 刷新新闻列表」获取实时新闻（无网络时自动回退内置示例新闻），直接**点选新闻卡片**即可爬取该篇评论，无需复制链接。
- 点选后展示：
  - 概览指标：评论总数、数据来源、最早 / 最新评论时间
  - ☁️ **评论词云**（jieba 中文分词，按词频渲染字号；无需额外字体）
  - 💡 **情感分析**（SnowNLP 优先，缺失时内置词典兜底）：正面 / 中性 / 负面分布 + 柱状图 + 整体倾向
  - 🔥 表情 / 表态 Top 10 柱状图
  - 💬 热门评论卡片（按点赞排序）
  - 📋 全部评论表格（含每条情感标签）+ 下载 CSV
- 爬虫优先使用懂球帝**网页版评论接口**，失败自动回退到 **App 老接口**；若均不可用，则回退到内置示例数据并在页面顶部提示，保证界面始终可演示。

## 本地运行

```bash
pip install -r requirements.txt
streamlit run app.py
# 浏览器打开提示的地址（默认 http://localhost:8501/）
```

## 部署到 Streamlit Community Cloud

1. 将本目录推送到你的 GitHub 公开仓库（仓库根目录需包含 `app.py`、`dongqiudi_comments.py`、`requirements.txt`）。
2. 打开一键部署链接（把 `<user>`/`<repo>` 换成你的仓库）：

   ```
   https://share.streamlit.io/deploy?repository=<user>/<repo>&branch=main&mainModule=app.py
   ```

3. 用你的 Streamlit 账号（GitHub 登录）点击 **Deploy** 即可，之后每次 `git push` 自动重新部署。

## 合规声明

本应用仅用于**个人学习、数据研究**。请自觉遵守目标网站的 `robots.txt` 与相关法律规定，
不要将抓取的数据用于商业用途或对外分发；如接口调整导致无法访问请降低频率或暂停使用。
