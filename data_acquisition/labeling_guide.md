# 游戏高光截图标注规范

> 当前生产推理范围仅为 `penta_kill`。目录仍保留三分类扩展能力，但新一轮五杀
> 模型训练只能使用经过复核的 class 0 五杀框；不得继续把五杀写为 class 1。

## 目录职责

```text
data_acquisition/
├── raw_images/                   # 爬虫原图，只读，不在此目录保存标注
│   ├── lol/
│   └── csgo/
├── annotations/anylabeling/      # AnyLabeling JSON 源标注
│   ├── lol/
│   └── csgo/
├── yolo_dataset/                 # 导出并划分后的 YOLO 数据集
│   ├── images/{train,val,test}/
│   └── labels/{train,val,test}/
└── classes.txt                   # 唯一类别顺序来源
```

原图、AnyLabeling JSON 和 YOLO TXT 必须分层保存。不要直接修改或重命名
`raw_images/` 中的文件，否则 `dataset_images_metadata.csv` 中的路径会失效。

## 类别与框选规则

类别顺序固定，不得在标注软件或导出阶段重新排序：

| ID  | 标签           | 标注对象                                   |
| --- | ------------ | -------------------------------------- |
| 0   | `penta_kill` | 明确表示五杀、Pentakill 或 ACE 五杀结果的文字、横幅或徽章区域 |
| 1   | `multi_kill` | 明确表示二杀、三杀、四杀等连续多杀结果的文字、横幅或徽章区域         |
| 2   | `kill_feed`  | 击杀信息栏中的单条击杀记录，包含击杀者、武器图标和被击杀者          |

- 框应紧贴完整 UI 元素，不要框整张游戏画面。
- 同一个结果提示不得同时标为 `penta_kill` 和 `multi_kill`；五杀始终使用
  `penta_kill`，二至四杀使用 `multi_kill`。
- 击杀栏有多条记录时，每一行分别标一个 `kill_feed` 框。
- 一张图片可以同时包含结果提示框和多个 `kill_feed` 框。
- UI 被裁切、严重模糊或文字无法确认时不要标注该目标。
- 没有上述目标的图片作为负样本保留，生成空标签文件。

## AnyLabeling 操作

1. 在 AnyLabeling 中加载 `classes.txt` 的三个类别，保持原始顺序。
2. 分别打开 `raw_images/lol/` 和 `raw_images/csgo/` 作为图片目录。
3. 将标注输出目录分别设为 `annotations/anylabeling/lol/` 和
   `annotations/anylabeling/csgo/`，保存 JSON 源标注。
4. 完成人工复核后导出 YOLO Detection 格式，并按数据划分把图片和同名 TXT
   放入 `yolo_dataset/images/` 与 `yolo_dataset/labels/` 对应子目录。
5. 每张图片与标签必须同名，例如 `lol_xxx.jpg` 对应 `lol_xxx.txt`。

建议按 8:1:1 划分 train、val、test，并在划分时保持 LOL 与 CSGO 样本比例接近。

## 20 张种子集与自动标注闭环

### 种子集原则

`bootstrap_seed_manifest.json` 固定记录首轮 20 张人工种子图、train/val 划分和
归一化框坐标。当前为 16 张 train、4 张 val，覆盖：

- 明确的 `penta_kill` 横幅；
- CSGO 右上角逐行 `kill_feed`；
- 1 个明确“四连破”的 `multi_kill`；
- train、val 各 1 张无目标负样本。

当前 `multi_kill` 只有一个可靠种子框。它可以验证流水线是否跑通，但不能用于
判断该类别的召回率或泛化能力。正式训练前至少补充 20 个来自不同画面、英雄和
分辨率的 `multi_kill` 实例，并在 val/test 中各保留独立样本。

不要把同一局视频的相邻帧拆到 train 和 val/test。画面近乎重复的截图必须放在
同一集合，否则验证指标会虚高。

### 执行流程

```powershell
# 生成 16/4 的种子 YOLO 数据和 AnyLabeling JSON
python data_acquisition/bootstrap_autolabel.py prepare

# CPU 环境默认使用 yolo11n、512 输入、20 epochs
python data_acquisition/bootstrap_autolabel.py train

# 对种子集之外的原图生成 AnyLabeling 候选 JSON
python data_acquisition/bootstrap_autolabel.py predict
```

也可执行 `python data_acquisition/bootstrap_autolabel.py all` 串行完成三步。
训练权重和日志写入 `data_acquisition/runs/bootstrap20/`；候选标注写入
`annotations/auto_anylabeling/{lol,csgo}/`，候选审核状态写入
`annotations/auto_anylabeling/review_manifest.csv`。

自动标注目录不会覆盖 `annotations/anylabeling/` 中的人工真值。模型输出只能
作为预标注建议，不能直接加入 YOLO 训练集。

## 人工复核流程

按 `review_manifest.csv` 逐张处理，不能只检查“模型有框”的图片；零预测图片也
可能存在漏检。建议在 AnyLabeling 中按以下顺序复核：

1. 删除背景、角色、比分板等误检框。
2. 修正类别，特别检查 `penta_kill` 是否被错分为 `multi_kill`。
3. 调整过宽、过窄、截断文字或包含大量背景的框。
4. 补画模型漏掉的结果提示和每一行 `kill_feed`。
5. 确认无目标图片保持空 shapes，而不是因为未检查而为空。
6. 保存后将 `review_status` 更新为 `accepted`、`rejected` 或 `needs_rework`，并填写
   `reviewer`；有争议时在 `notes` 说明原因。
7. 只有 `accepted` JSON 才能移入 `annotations/anylabeling/{lol,csgo}/` 并导出
   YOLO TXT。

### 单张验收清单

- 标签名称和 ID 与 `classes.txt` 完全一致；
- 每个框只覆盖一个完整 UI 目标；
- 同一五杀提示没有重复框或双标签；
- 击杀栏逐行标注，无合并多行的大框；
- 图片内所有可辨识目标均已处理；
- 模糊、遮挡超过一半或语义不确定的候选已删除；
- 图片文件名、JSON、YOLO TXT 三者同名。

### 迭代训练

首轮建议人工复核模型最不确定的图片：置信度低、预测数为零、同图类别冲突的
样本优先。每轮只把已验收数据加入 train，固定 val/test 不参与自动回流。新增
一批审核通过的样本后重新训练，再比较固定验证集上的 Precision、Recall 和
mAP50；若指标下降，先检查新增标注质量和类别分布，不要仅增加 epochs。
