import os
import os.path
from ADFSDir import ADFSDir
from ADFSFile import ADFSFile
from ADFSVolume import ADFSVolume
from MetaDB import MetaDB
import DosType
from amitools.fs.block.BootBlock import BootBlock
from amitools.fs.blkdev.BlkDevFactory import BlkDevFactory
from amitools.fs.blkdev.DiskGeometry import DiskGeometry
import amitools.util.KeyValue as KeyValue

class Imager:
  def __init__(self):
    self.meta_db = None
    self.total_bytes = 0

  def get_total_bytes(self):
    return self.total_bytes

  # ----- unpack -----
  
  def unpack(self, volume, out_path):
    # check for volume path
    vol_name = volume.name
    if not os.path.exists(out_path):
      vol_path = out_path
    else:
      path = os.path.abspath(out_path)
      vol_path = os.path.join(path, vol_name)
    if os.path.exists(vol_path):
      raise IOError("Unpack directory already exists: "+vol_path)
    # check for meta file
    meta_path = vol_path + ".xdfmeta"
    if os.path.exists(meta_path):
      raise IOError("Unpack meta file already exists:"+meta_path)
    # check for block dev file
    blkdev_path = vol_path + ".blkdev"
    if os.path.exists(blkdev_path):
      raise IOError("Unpack blkdev file aready exists:"+blkdev_path)
    # create volume path
    self.meta_db = MetaDB()
    self.unpack_root(volume, vol_path)
    # save meta db
    self.meta_db.set_volume_name(volume.name)
    self.meta_db.set_root_meta_info(volume.get_meta_info())
    self.meta_db.set_dos_type(volume.boot.dos_type)
    self.meta_db.save(meta_path)
    # save boot code
    if volume.boot.boot_code != None:
      boot_code_path = vol_path + ".bootcode"
      f = open(boot_code_path,"wb")
      f.write(volume.boot.boot_code)
      f.close()
    # save blkdev
    f = open(blkdev_path,"wb")
    f.write("%s\n" % volume.blkdev.get_chs_str())
    f.close()
    
  def unpack_root(self, volume, vol_path):
    self.unpack_dir(volume.get_root_dir(), vol_path)
  
  def unpack_dir(self, dir, path):
    if not os.path.exists(path):
      os.mkdir(path)
    for e in dir.get_entries():
      self.unpack_node(e, path)
  
  def unpack_node(self, node, path):
    name = node.name.name
    # store meta info
    if self.meta_db != None:
      node_path = node.get_node_path_name()
      self.meta_db.set_meta_info(node_path, node.meta_info)
    # sub dir
    if node.is_dir():
      sub_dir = os.path.join(path, name)
      os.mkdir(sub_dir)
      for sub_node in node.get_entries():
        self.unpack_node(sub_node, sub_dir)
      node.flush()
    # file
    elif node.is_file():
      data = node.get_file_data()
      node.flush()
      file_path = os.path.join(path, name)
      fh = open(file_path, "wb")
      fh.write(data)
      fh.close()
      self.total_bytes += len(data)
  
  # ----- pack -----
  
  def pack(self, in_path, image_file, force=True, options=None):
    self.pack_begin(in_path)
    blkdev = self.pack_create_blkdev(in_path, image_file, force, options)
    if blkdev == None:
      raise IOError("Can't create block device for image: "+in_path)
    volume = self.pack_create_volume(in_path, blkdev)
    if not volume.valid:
      raise IOError("Can't create volume for image: "+in_path)
    self.pack_root(in_path, volume)
    self.pack_end(in_path, volume)

  def pack_begin(self, in_path):
    # remove trailing slash
    if in_path[-1] == '/':
      in_path = in_path[:-1]
    meta_path = in_path + ".xdfmeta"
    if os.path.exists(meta_path):
      self.meta_db = MetaDB()
      self.meta_db.load(meta_path)
  
  def pack_end(self, in_path, volume):
    boot_code_path = in_path + ".bootcode"
    if os.path.exists(boot_code_path):
      # read boot code
      f = open(boot_code_path, "rb")
      data = f.read()
      f.close()
      # write boot code
      bb = volume.boot
      ok = bb.set_boot_code(data)
      if ok:
        bb.write()
      else:
        raise IOError("Invalid Boot Code")
  
  def pack_create_blkdev(self, in_path, image_file, force=True, options=None):
    # try to read options from blkdev file
    if options == None or len(options) == 0:
      blkdev_path = in_path + ".blkdev"
      if os.path.exists(blkdev_path):
        f = open(blkdev_path, "rb")
        options = {}
        for line in f:
          KeyValue.parse_key_value_string(line, options)
        f.close()
    f = BlkDevFactory()
    return f.create(image_file, force=force, options=options)
    
  def pack_create_volume(self, in_path, blkdev):
    if self.meta_db != None:
      name = self.meta_db.get_volume_name()
      meta_info = self.meta_db.get_root_meta_info()
      dos_type = self.meta_db.get_dos_type()
    else:
      # try to derive volume name from image name
      if in_path == None or in_path == "":
        raise IOError("Invalid pack input path!")
      # remove trailing slash
      if in_path[-1] == '/':
        in_path = in_path[:-1]
      name = os.path.basename(in_path)
      meta_info = None
      dos_type = DosType.DOS0
    volume = ADFSVolume(blkdev)
    volume.create(name, meta_info, dos_type=dos_type)
    return volume
  
  def pack_root(self, in_path, volume):
    self.pack_dir(in_path, volume.get_root_dir())
  
  def pack_dir(self, in_path, parent_node):
    path = os.path.abspath(in_path)
    if not os.path.exists(path):
      raise IOError("Pack directory does not exist: "+path)
    for name in os.listdir(in_path):
      sub_path = os.path.join(in_path, name)
      self.pack_entry(sub_path, parent_node)
      
  def pack_entry(self, in_path, parent_node):
    ami_name = os.path.basename(in_path)
    # retrieve meta info for path from DB
    if self.meta_db != None:
      ami_path = parent_node.get_node_path_name()
      if ami_path != "":
        ami_path += "/" + ami_name
      else:
        ami_path = ami_name
      meta_info = self.meta_db.get_meta_info(ami_path)
    else:
      meta_info = None    

    # pack directory
    if os.path.isdir(in_path):
      node = parent_node.create_dir(ami_name, meta_info, False)
      for name in os.listdir(in_path):
        sub_path = os.path.join(in_path, name)
        self.pack_entry(sub_path, node)
      node.flush()
    # pack file
    elif os.path.isfile(in_path):
      # read file
      fh = open(in_path, "rb")
      data = fh.read()
      fh.close()
      node = parent_node.create_file(ami_name, data, meta_info, False)
      node.flush()
      self.total_bytes += len(data)
