from time import time
from typing import Optional, Union, Tuple, List, Dict
from os import path
import torch
from torch.utils.data import DataLoader, Dataset, SubsetRandomSampler
from torch.nn import Module
from torch.optim import Optimizer
from sklearn.model_selection import KFold
import numpy as np
from logging import Logger, getLogger, Formatter, FileHandler, StreamHandler, INFO


def get_train_info_logger(
        filepath:str,
        show_in_terminal = False,
    )->Logger:
    formatter = Formatter("[%(asctime)s]: %(levelname)-8s - %(message)s")
    file_handler = FileHandler(filepath)
    file_handler.setFormatter(formatter)
    stream_handler = StreamHandler()
    stream_handler.setFormatter(formatter)
    logger = getLogger()
    logger.addHandler(file_handler)
    if show_in_terminal:
        logger.addHandler(stream_handler)
    logger.setLevel(INFO)
    return logger


def train_model(
    training_model: Module,
    dloader: dict[str, DataLoader],
    loss_func: Module,
    optimizer: Optimizer,
    logger: Logger,
    root_path: str = ".",
    model_name: Optional[str] = None,
    epoches: int = 10,
    start_epoch: int = 0,
    loss: Dict[str, list] = {"train": [], "val": []},
    best_val_loss: float = float("inf"),
    device: str = "cuda",
):
    """
    训练模型的函数。也可以重启训练。

    参数:
    - training_model: 正在训练的模型。
    - dloader: 包含训练和验证数据的数据加载器字典。需要为以下形式: {"train": train_loader, "val": val_loader}
    - loss_func: 损失函数。
    - optimizer: 优化器。
    - logger: 打印训练信息的日志记录器。
    - save_path: 模型保存路径,默认为当前目录。
    - save_name: 模型保存名称,默认为模型类的名称。
    - epoches: 训练轮数,默认为10。
    - start_epoch: 从哪个轮数开始训练,默认为0。
    - loss: 存储训练和验证过程的损失值的字典,默认为空需要为以下形式: {"train": [], "val": []}。
    """
    # 如果未提供save_name,则使用模型的类名
    if model_name is None:
        model_name = type(training_model).__name__

    # 开始训练和验证过程
    for e in range(start_epoch, start_epoch + epoches):
        start_time = time()
        logger.info(f"Epoch {e} start")
        floss = train_single_fold(
            training_model=training_model,
            dloader=dloader,
            loss_func=loss_func,
            optimizer=optimizer,
            device=device,
            logger=logger,
        )
        loss["train"].append(floss[0])
        loss["val"].append(floss[1])
        if loss["val"][-1] < best_val_loss:
            best_val_loss = loss["val"][-1]
            save_checkpoints(
                training_model,
                optimizer,
                root_path,
                model_name,
                loss,
                e=e,
                suffix="best",
                best_loss=best_val_loss,
                logger=logger,
            )
        save_checkpoints(
            training_model,
            optimizer,
            root_path,
            model_name,
            loss,
            e=e,
            best_loss=best_val_loss,
            logger=logger,
        )
        end_time = time()
        logger.info(f"Epoch {e} end with time {(end_time - start_time)/3600:.4f}")
        logger.info("====================")


def save_checkpoints(
    training_model: Module,
    optimizer: Optimizer,
    logger: Logger,
    root_path: str,
    model_name: str,
    loss: Dict[str, float],
    e: int,
    best_loss: float,
    suffix: str = "latest",
):
    """
    保存训练模型的检查点。

    此函数用于保存模型在特定训练阶段的状态,包括模型的参数、优化器的状态、当前的损失值和训练的轮次。
    这使得模型能够在未来的某个时间点继续训练或者进行评估。

    参数:
    - training_model (Module): 当前训练的模型。
    - optimizer (Optimizer): 当前使用的优化器。
    - logger (Logger): 用于记录训练过程的日志记录器。
    - root_path (str): 保存检查点的根目录路径。
    - model_name (str): 模型的名称,用于生成保存文件的名称。
    - loss (Dict[str, float]): 当前模型的损失值,通常包括一个或多个损失项。
    - e (int): 当前训练的轮次
    - best_loss (float): 所有轮次里的最佳损失值
    - suffix (str): 模型的训练轮次或者标识,用于生成保存文件的名称,默认为"latest"。
    """
    # 生成保存模型检查点的完整路径
    save_path = path.join(root_path, f"{model_name}_{suffix}.ckpt")

    # 保存模型检查点,包括当前训练轮次、模型状态字典、优化器状态字典和损失值
    torch.save(
        {
            "epoch": e,
            "model_state_dict": training_model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "loss": loss,
            "best_loss":best_loss
        },
        save_path,
    )
    logger.info(f"Save {suffix} model to {save_path}")


def train_single_fold(
    training_model: Module,
    dloader: dict[str, DataLoader],
    loss_func: Module,
    optimizer: Optimizer,
    logger: Logger,
    device: str = "cuda",
) -> float:
    """
    训练模型的函数。也可以重启训练。

    参数:
    - training_model: 正在训练的模型。
    - dloader: 包含训练和验证数据的数据加载器字典。需要为以下形式: {"train": train_loader, "val": val_loader}
    - loss_func: 损失函数。
    - optimizer: 优化器。
    - logger: 用于记录训练进度的日志记录器。
    - device: 用于训练的设备。默认为 "cuda"。
    """
    # 计算训练和验证数据集的大小
    dset_size = {s: len(dset) for s, dset in dloader.items() if s in ["train", "val"]}

    # 开始训练和验证过程
    loss = []
    # 对于每个epoch,分别处理训练和验证数据集
    for dataset in ["train", "val"]:
        logger.info(f"{dataset} start")
        loss_epoch = 0

        # 根据数据集设置模型的训练/评估模式
        if dataset == "train":
            training_model.train()
        else:
            training_model.eval()

        # 遍历数据集中的所有数据
        for batch in dloader[dataset]:
            optimizer.zero_grad()

            # 将数据移动到指定设备
            batch = [item.to(device) for item in batch]
            targets = batch[-1]

            # 根据当前是否在训练阶段, 决定是否启用梯度计算
            with torch.set_grad_enabled(dataset == "train"):
                outputs = training_model(*batch[0:-1])
                current_loss = loss_func(outputs, targets)

                # 在训练阶段,执行反向传播和优化步骤
                if dataset == "train":
                    current_loss.backward()
                    optimizer.step()

            # 累加当前批次的损失值
            # logger.info(f"{dataset} outputs: {outputs}")
            loss_epoch += current_loss.item() * batch[0].size(0)
        logger.info(f"{dataset} batch end with loss {loss_epoch:.4f}")
        # 计算并存储当前阶段的平均损失值
        loss.append(loss_epoch / dset_size[dataset])
        logger.info(f"{dataset} end with loss {loss[-1]:.4f}")

    return loss


def cross_validate(
    dataset: Dataset,
    training_model: Module,
    optim: Optimizer,
    loss_func: Module,
    logger: Logger,
    n_splits: int = 5,
    batch_size: int = 128,
    epoches: int = 10,
    start_epoches: int = 0,
    root_path: str = ".",
    single_fold_func: callable = train_single_fold,
    prefix: Optional[str] = None,
    loss: Dict[str, float] = {"mean": [], "std": []},
    best_loss: float = float("inf"),
    device: str = "cuda",
):
    """
    对给定的数据集进行交叉验证训练和评估。

    参数:
    - dataset: Dataset 实例,包含所有训练和验证数据。
    - training_model: Module 实例,待训练的模型。
    - optim: Optimizer 实例,用于模型训练的优化器。
    - loss_func: Module 实例,用于计算损失的函数。
    - logger: Logger 用于记录训练过程的日志Logger。
    - n_splits: int,默认为5,表示交叉验证的折数。
    - batch_size: int,默认为128,表示每个批次的样本数。
    - epoches: int,默认为10,表示训练的轮数。
    - start_epoches: int,默认为0,表示开始训练的轮数。
    - root_path: str,默认为".",表示保存模型和结果的根路径。
    - model_name: Optional[str],模型的名称,如未提供,则使用模型的类名。
    - loss: Dict[str, float],用于存储每轮训练的损失均值和标准差。
    - best_loss: float, 用于存储最佳损失。
    - device: str,默认为"cuda",表示设备类型。
    """
    # 如果未提供save_name,则使用模型的类名
    if prefix is None:
        prefix = type(training_model).__name__
    # 初始化KFold对象进行交叉验证分割
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    # 初始化最佳损失为无穷大
    dloader = []
    for train_idx, val_idx in kf.split(dataset):
        dloader.append(
            {
                "train": DataLoader(
                    dataset,
                    batch_size=batch_size,
                    sampler=SubsetRandomSampler(train_idx),
                ),
                "val": DataLoader(
                    dataset,
                    batch_size=batch_size,
                    sampler=SubsetRandomSampler(val_idx),
                ),
            }
        )
    # 遍历每个epoch
    for e in range(start_epoches, start_epoches + epoches):
        start_time = time()
        logger.info(f"Epoch {e} start")
        fold_loss = []
        # 遍历每个交叉验证折
        for fold in range(n_splits):
            logger.info(f"Fold {fold} start")
            # 创建训练和验证的数据加载器
            # 训练单个折并获取损失
            floss = single_fold_func(
                training_model=training_model,
                dloader=dloader[fold],
                loss_func=loss_func,
                optimizer=optim,
                device=device,
                logger=logger,
            )
            fold_loss.append(floss[-1])
            logger.info(f"Fold {fold} end")
        # 计算当前epoch的损失均值和标准差
        fold_loss_mean = np.mean(fold_loss)
        fold_loss_std = np.std(fold_loss)
        loss["mean"].append(fold_loss_mean)
        loss["std"].append(fold_loss_std)
        end_time = time()
        logger.info(
            f"End epoch {e} with {n_splits} folds in {(end_time-start_time)/3600:.4f} hours with loss {fold_loss_mean:.4f} +/- {fold_loss_std:.4f}"
        )
        # 如果当前损失均值为最佳,则保存模型
        if fold_loss_mean < best_loss:
            best_loss = fold_loss_mean
            save_checkpoints(
                training_model=training_model,
                optimizer=optim,
                model_name=prefix,
                root_path=root_path,
                loss=loss,
                e=e,
                suffix="best",
                best_loss=best_loss,
                logger=logger,
            )

        # 保存最新模型
        save_checkpoints(
            training_model=training_model,
            optimizer=optim,
            model_name=prefix,
            root_path=root_path,
            e=e,
            loss=loss,
            best_loss=best_loss,
            logger=logger,
        )
