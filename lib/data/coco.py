import os
import os.path as osp
import sys
import numpy as np

import torch
import torch.utils.data as data
import cv2

from pycocotools.coco import COCO
from .config import HOME

COCO_ROOT = osp.join(HOME, 'data/coco/')
IMAGES = 'images'
ANNOTATIONS = 'annotations'
COCO_API = 'PythonAPI'
INSTANCES_SET = 'instances_{}.json'
COCO_CLASSES = ('person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus',
                'train', 'truck', 'boat', 'traffic light', 'fire', 'hydrant',
                'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog',
                'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra',
                'giraffe', 'backpack', 'umbrella', 'handbag', 'tie',
                'suitcase', 'frisbee', 'skis', 'snowboard', 'sports ball',
                'kite', 'baseball bat', 'baseball glove', 'skateboard',
                'surfboard', 'tennis racket', 'bottle', 'wine glass', 'cup',
                'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
                'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza',
                'donut', 'cake', 'chair', 'couch', 'potted plant', 'bed',
                'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote',
                'keyboard', 'cell phone', 'microwave oven', 'toaster', 'sink',
                'refrigerator', 'book', 'clock', 'vase', 'scissors',
                'teddy bear', 'hair drier', 'toothbrush')


def get_label_map(label_file):
    if os.path.isfile(label_file):
        label_map = {}
        labels = open(label_file, 'r')
        for line in labels:
            ids = line.split(',')
            label_map[int(ids[0])] = int(ids[1])
        return label_map
    else:
        print("Warning: can't train on COCO sets")
        return None


class COCOAnnotationTransform(object):
    """Transforms a COCO annotation into a Tensor of bbox coords and label index
    Initilized with a dictionary lookup of classnames to indexes
    """

    def __init__(self, is_scale=True):
        self.label_map = get_label_map(osp.join(COCO_ROOT, 'coco_labels.txt'))
        self.is_scale = is_scale

    def __call__(self, target, width, height):
        """
        Args:
            target (dict): COCO target json annotation as a python dict
            height (int): height
            width (int): width
        Returns:
            TODO a list containing lists of bounding boxes  [bbox coords, class idx]
        """
        scale = np.array([width, height, width, height])
        res = []
        for obj in target:
            if 'bbox' in obj:
                bbox_orig = obj['bbox']
                bbox = [int(bbox_orig[0]) - 1, int(bbox_orig[1]) - 1,
                        int(bbox_orig[2] + bbox_orig[0]) - 1, int(bbox_orig[3] + bbox_orig[1]) - 1]

                label_idx = self.label_map[obj['category_id']] - 1
                if self.is_scale:
                    final_box = list(np.array(bbox) / scale)  # scale to [0, 1]
                else:
                    final_box = list(np.array(bbox))
                final_box.append(label_idx)
                res += [final_box]  # [xmin, ymin, xmax, ymax, label_idx]
            else:
                # TODO delete it
                print("no bbox problem!")

        return res  # [[xmin, ymin, xmax, ymax, label_idx], ... ]


# TODO zheli base???
class Dataset(object):
    """The base class for dataset classes.
    To use it, create a new class that adds functions specific to the dataset
    you want to use. For example:
    class CatsAndDogsDataset(Dataset):
        def load_cats_and_dogs(self):
            ...
        def load_mask(self, image_id):
            ...
        def image_reference(self, image_id):
            ...
    See COCODataset and ShapesDataset as examples.
    """

    def __init__(self, class_map=None):
        self._image_ids = []
        self.img_cnt = 0
        self.image_info = []
        # Background is always the first class
        self.class_info = [{"source": "", "id": 0, "name": "BG"}]
        self.source_class_ids = {}

    # self.add_class("coco", i, coco.loadCats(i)[0]["name"])
    def add_class(self, source, class_id, class_name):
        assert "." not in source, "Source name cannot contain a dot"
        # Does the class exist already?
        for info in self.class_info:
            if info['source'] == source and info["id"] == class_id:
                # source.class_id combination already available, skip
                return
        # Add the class
        self.class_info.append({
            "source": source,  # data set name
            "id": class_id,
            "name": class_name,
        })

    def add_image(self, source, image_id, path, **kwargs):
        image_info = {
            "id": image_id,  # img id
            "source": source,  # dataset name, e.g. coco, voc
            "path": path,  # img path
        }
        image_info.update(kwargs)  # default add (key, value)
        self.image_info.append(image_info)
        self._image_ids.append(self.img_cnt)
        self.img_cnt += 1


class CocoDataset(Dataset):
    def load_coco(self, dataset_dir, subset, year='2014', class_ids=None,
                  class_map=None):
        """Load a subset of the COCO dataset.
        dataset_dir: The root directory of the COCO dataset.
        subset: What to load (train, val, minival, valminusminival)
        year: What dataset year to load (2014, 2017) as a string, not an integer
        class_ids: If provided, only loads images that have the given classes.
        class_map: TODO: Not implemented yet. Supports maping classes from
            different datasets to the same class ID.
        return_coco: If True, returns the COCO object.
        auto_download: Automatically download and unzip MS-COCO images and annotations
        """

        coco = COCO("{}/annotations/instances_{}{}.json".format(dataset_dir, subset, year))
        if subset == "minival" or subset == "valminusminival":
            subset = "val"
        image_dir = "{}/{}{}".format(dataset_dir, subset, year)

        # Load all classes or a subset?
        if not class_ids:
            # All classes
            class_ids = sorted(coco.getCatIds())

        # All images or a subset?
        if class_ids:  # if not none, only keep these class_ids
            image_ids = []
            for id in class_ids:
                image_ids.extend(list(coco.getImgIds(catIds=[id])))
            # Remove duplicates
            image_ids = list(set(image_ids))
        else:
            # All images
            image_ids = list(coco.imgs.keys())

        # Add classes
        for i in class_ids:
            self.add_class("coco", i, coco.loadCats(i)[0]["name"])

        # Add images
        for i in image_ids:
            self.add_image(
                "coco", image_id=i,
                path=os.path.join(image_dir, coco.imgs[i]['file_name']),
                width=coco.imgs[i]["width"],
                height=coco.imgs[i]["height"],
                annotations=coco.loadAnns(coco.getAnnIds(
                    imgIds=[i], catIds=class_ids, iscrowd=None)))


class COCODetection(data.Dataset):
    """`MS Coco Detection <http://mscoco.org/dataset/#detections-challenge2016>`_ Dataset.
    Args:
        root (string): Root directory where images are downloaded to.
        set_name (string): Name of the specific set of COCO images.
        transform (callable, optional): A function/transform that augments the
                                        raw images`
        target_transform (callable, optional): A function/transform that takes
        in the target (bbox) and transforms it.
    """

    def __init__(self, root, image_set=['train', 'valminusminival'], transform=None,
                 target_transform=COCOAnnotationTransform(), dataset_name='MS COCO'):
        sys.path.append(osp.join(root, COCO_API))
        self.root = root
        self.data_set = CocoDataset()
        for subset in image_set:
            self.data_set.load_coco(root, subset)

        self.ids = self.data_set._image_ids
        self.transform = transform
        self.target_transform = target_transform
        self.name = dataset_name

    def __getitem__(self, index):
        im, gt, h, w = self.pull_item(index)
        return im, gt

    def __len__(self):
        return len(self.ids)

    def pull_item(self, index):
        img_id = self.ids[index]

        target = self.data_set.image_info[img_id]["annotations"]
        path = self.data_set.image_info[img_id]["path"]
        assert osp.exists(path), 'Image path does not exist: {}'.format(path)
        img = cv2.imread(path)  # Shape(H, W, C)
        height, width, channels = img.shape

        if self.target_transform is not None:  # process to [xmin,ymin,xmax,ymax, label]
            target = self.target_transform(target, width, height)

        if self.transform is not None:  # process to 300X300
            target = np.array(target)
            if target.size == 0:
                img, boxes, labels = self.transform(img)
            else:
                img, boxes, labels = self.transform(img, target[:, :4], target[:, 4])

            img = img[:, :, (2, 1, 0)]  # to rgb
            target = np.hstack((boxes, np.expand_dims(labels, axis=1)))
        return torch.from_numpy(img).permute(2, 0, 1), target, height, width
