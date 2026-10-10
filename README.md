# Batch OA Downloader

一个用于 Codex 的批量开放获取文献下载 Skill。它可以读取 BibTeX、RIS 或 RTS 文献表，逐条查询合法开放获取状态，下载并验证可免费获取的 PDF，同时为未找到免费全文的记录生成清晰报告。

## 功能

- 支持 `.bib`、`.ris` 和 `.rts` 文献表
- 基于 DOI 或题名查询 OpenAlex；配置邮箱后可补充查询 Unpaywall
- 自动下载合法开放获取 PDF
- 验证 `%PDF-` 文件签名，拒绝把 HTML、登录页或错误页保存为 PDF
- 输出 CSV 状态表、JSON 审计清单和 ZIP 压缩包
- 标记未发现免费全文、元数据无法匹配及下载失败的记录
- 内置输入规模、网络地址、重定向、下载体积和输出目录保护

## 安装

将整个 `batch-oa-downloader` 目录复制到以下任一位置：

```text
# 当前项目使用
<project>/.codex/skills/batch-oa-downloader/

# 当前用户全局使用
~/.codex/skills/batch-oa-downloader/
```

安装后的核心结构：

```text
batch-oa-downloader/
├── SKILL.md
├── README.md
├── agents/
│   └── openai.yaml
└── scripts/
    └── batch_oa_download.py
```

## 在 Codex 中使用

上传或提供 BibTeX/RIS 文件后调用：

```text
$batch-oa-downloader 请逐条检查这个文献表，并下载其中可以合法免费获取的 PDF。
```

Skill 会返回：

- `PDFs/`：验证成功的开放获取 PDF
- `access_report.csv`：适合人工查看和筛选的逐篇状态表
- `manifest.json`：包含来源、URL、文件名和 SHA-256 的审计记录
- `<结果目录>.zip`：PDF 与报告的完整压缩包

## 命令行使用

仅依赖 Python 3 标准库：

```powershell
python scripts/batch_oa_download.py `
  --input "references.bib" `
  --out "oa-results" `
  --zip
```

可选配置 Unpaywall 联系邮箱：

```powershell
$env:UNPAYWALL_EMAIL = "researcher@example.org"
python scripts/batch_oa_download.py --input "references.ris" --out "oa-results" --zip
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--email ADDRESS` | 启用 Unpaywall，并为 API 请求提供联系邮箱 |
| `--delay SECONDS` | 文献记录之间的等待时间，默认 0.5 秒 |
| `--timeout SECONDS` | 单次网络请求超时，默认 30 秒 |
| `--max-records N` | 最大记录数，默认 500，硬上限 2000 |
| `--max-pdf-mib N` | 单个 PDF 大小上限，默认 100 MiB |
| `--dry-run` | 仅解析文献表，不访问网络 |
| `--zip` | 生成包含 PDF 和报告的 ZIP 文件 |

输出目录必须不存在或为空，防止旧文件被误打包。

## 状态说明

| 状态 | 含义 |
|---|---|
| `open_access_downloaded` | 已找到、下载并验证开放获取 PDF |
| `open_access_found_download_failed` | 找到 OA 候选地址，但未得到有效 PDF |
| `closed_or_no_oa_found` | 已解析元数据，但未发现合法免费 PDF；不等同于证明所有渠道均收费 |
| `metadata_unresolved` | 无法可靠匹配文献元数据，需要人工核对 |
| `invalid_record` | 记录缺少可用 DOI 和题名 |

## 安全与合规

本项目只使用合法开放获取来源，不绕过付费墙、登录、验证码、DRM 或机构访问控制。

防御措施包括：

- 只接受公网 HTTPS 下载地址
- 阻止本机、内网、URL 凭据和危险重定向
- 限制输入、API 响应、批次数量与 PDF 大小
- PDF 分块下载到临时文件，验证后原子落盘
- 对仅含题名的记录执行匹配置信度检查
- 截断并脱敏报告中的网络错误信息

## 已知限制

- “未发现开放版本”并不意味着文献一定收费，机构订阅或作者个人主页仍可能提供合法访问途径。
- 部分仓储地址会返回动态页面、临时拒绝或失效链接，这类记录会标为 `open_access_found_download_failed`。
- 当前工作流只下载正文 PDF，不自动下载 Supporting Information。

## 许可证

发布前请根据目标仓库的许可证策略添加或沿用对应许可证。本 Skill 本身不会自动推断或修改许可证。
