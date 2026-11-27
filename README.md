# 跨境论坛中英文纪要的核对与披露

跨境论坛的虚构发言速记、勘误、稿件授权和面向各读者的机构名录。

## 资料

`materials/` 保存本地合成资料，每行是一个 UTF-8 JSON 对象。业务记录编号只在所在文件中唯一。各来源文书保持原有措辞，便于按原文定位。

notes 的日期与名录任期使用统一公历。session 表示于会内核对，public 表示可对外发稿，授权以 permissions 为准。读者可辨认所指的公开名录是本项目提供的有限合成资料。

### directory.jsonl

字段为 `id`、`name`、`aliases`、`organization`、`role`、`period`、`routes`。发稿所依据的合成公开名录。period 为任职起止月份，便于区分同一职位在不同时段的人员。

### notes.jsonl

字段为 `id`、`date`、`session`、`language`、`submitted`、`text`。速记、勘误和机构函以记录编号区分。submitted 为材料提交方。内容中可能转述其他人。

### permissions.jsonl

字段为 `id`、`time`、`material`、`audiences`、`selector`、`note`。授权对象按材料和文字区段记载。selector 为该原文中的准确选段，空字符串表示全文。新授权只作用于所列材料和受众。

### editions.jsonl

字段为 `id`、`audience`、`language`、`time`、`phase`、`text`、`basis`。编辑部已经保存的各版本草稿和发出文本。basis 是当时引用的材料编号。

## 资料核对

运行环境使用 Python 3.11.2 和标准库。进入项目目录运行以下命令，读取全部交接文件并核对字段、记录编号和资料引用。

```sh
python3 -m unittest discover -s tests -v
```

## 纪要编校工具 minutedesk

`minutedesk/` 是可反复使用的授权感知编校工具，纯标准库实现。术语随项目走
`config/synonyms.json`，引擎本身不内置任何专有名称。

### 处理链条

1. `loader.py` 读取并交叉校验四份 JSONL（字段、引用、选段原文、任期）。
2. `gazetteer.py` 由合成公开名录和同义词配置构建双语词表，含“银湾仓≠银湾线”
   这类后续字护栏和英文缩写（P. / Mr.）保护。
3. `identity.py` 区分同一人的别名、同职务历任者（按句内时态词与名录任期）、
   以及仅以联合代表团名义确认的事项；转述链中的被转述者与说话人分别记录。
4. `extract.py` 切句并标注说法性质（提议/确认/勘误/保留态度）、月份、
   适用方与范围限定（仅汇总指标、日期待确认等），相对月份换算后保留来源标记。
5. `arrange.py` 按活动+航线集合+月份做跨语种对齐；勘误链强制归并，
   要素缺失的句子不充当通配符；相近但不满足条件的安排只建立弱关联并说明原因，
   把分歧留给编辑。
6. `licensing.py` 按材料×受众×原文选段判定授权，选段不覆盖同材料其他句子，
   新授权不扩大到未列材料。
7. `reident.py` 只用合成名录和同版文字评估重识别：逐句称谓与跨句共指组合
   （职务+机构+航线+前任/现任）分别检查，已授权个人不计为风险。
8. `compose.py` 分受众出稿。每条取舍得 include / redact / review_only /
   exclude 之一，并记录决定它的许可编号或原话；共同来源能支撑的事实保留事实
   与限定，匿名后仍误导的说法只进“仅供核对”区，且保留共同商定与单方提议的区分。
9. `editions.py` 审计已存稿件（无授权引用、重识别、限定漂移），保存发送版快照，
   按输入指纹在重跑时比对取舍变化。

### 运行

资料目录视为不可信数据，应与脚本分开存放，并以隔离模式运行，避免解释器从
资料目录加载任何代码：

```sh
python3 -I run_minutedesk.py /path/to/materials -o /path/to/out
python3 -I run_minutedesk.py /path/to/materials -o /path/to/out --json
python3 -I run_minutedesk.py /path/to/materials -o /path/to/out \
    --compare /path/to/out/runs/<指纹>/result.json
```

输出：

- `public_zh.md` / `public_en.md`、`session_zh.md` / `session_en.md`：
  正文、仅供核对区、重识别评估和逐条审稿记录；
- `runs/<输入指纹>/result.json`：完整结构化结果，供编辑在项目中比较再出稿；
- `sent/`：实际发送过的版本快照及其当时审计结论，可回查。

### 安全边界

重识别评估不联网、不读取项目资料以外的任何来源；候选范围只来自合成公开名录
和传入版本文字。新增项目只需替换 `materials/` 与 `config/synonyms.json`，
引擎代码不需要改动。

