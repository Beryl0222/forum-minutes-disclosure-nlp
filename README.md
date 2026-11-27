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
