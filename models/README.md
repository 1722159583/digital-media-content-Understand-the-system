# 五杀检测模型说明

## 正式权重

- 推理权重：`models/game_highlight_train4_best.pt`
- 原始训练目录：`runs/detect/train-4/`
- 基础网络：YOLO11n
- 训练轮数：50
- 输入尺寸：640
- 对外任务：仅检测 `penta_kill`

服务使用稳定路径中的权重，`runs/` 目录保留训练参数、曲线、混淆矩阵和原始
`best.pt` 作为可复现实验材料。

## 类别兼容处理

`train-4` 的人工数据存在类别编号不一致：大部分五杀横幅被写成了原始 class 1
`multi_kill`，少量五杀为 class 0 `penta_kill`，训练、验证和测试集中没有
`kill_feed` 实例。因此当前服务只执行五杀检测：原始 class 0 和 class 1 均规范化
输出为 `penta_kill`，并在每个检测框中保留 `raw_class`、`raw_class_id` 便于追溯。

不得使用该权重宣称具备可靠的 `multi_kill` 或 `kill_feed` 检测能力。如需恢复
三分类，必须先按标注规范修正类别，再补充各类别独立 train/val/test 样本并重新训练。

## 当前验证结果

2026-07-26 使用 `data_acquisition/yolo_dataset/test/images/` 的 7 张独立图片、
置信度阈值 0.25 进行服务层烟雾测试：

| 项目 | 结果 |
| --- | ---: |
| 五杀正样本 | 6 |
| 负样本 | 1 |
| 检出的五杀正样本 | 5 |
| 漏检 | 1 |
| 负样本误报 | 0 |
| 样本级 Precision | 1.000 |
| 样本级 Recall | 0.833 |
| 热加载后单图耗时 | 0.06–0.13 秒 |
| 首次模型加载与首图推理 | 约 30.06 秒 |

训练日志最后一轮记录的 `mAP50=0.995`、`mAP50-95=0.7835` 主要反映原始
class 1 的 5 个验证框，不能解释为三分类总体指标。首次加载受 PyTorch/Ultralytics
初始化影响，部署时应在接收业务请求前调用 `load_model()` 预热；预热后满足单图
10 秒内处理的目标。
