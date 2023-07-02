# -*- coding: utf-8 -*-

#
# Author: Roland Pihlakas, 2021 - 2023
#
# roland@simplify.ee
#


import os
import sys
import io
import gzip
import pickle


import time
# import textwrap
import shutil
# import re
import codecs

# from progressbar import ProgressBar # NB! need to load it before init_logging is called else progress bars do not work properly for some reason

# import requests
import asyncio
# import aiohttp
import aiofiles                       # supports flush method
import aiofiles.os

import functools
# from functools import reduce
# import operator

# import numpy as np
# import pandas as pd

from Logger import get_now_str, init_colors, ansi_INTENSE, ansi_RED, ansi_GREEN, ansi_BLUE, ansi_CYAN, ansi_RESET



decompression_limit = 1 * 1024 * 1024 * 1024     # TODO: tune, config file



loop = asyncio.get_event_loop()



is_dev_machine = (os.name == 'nt')
debugging = (is_dev_machine and sys.gettrace() is not None) and (1 == 1)  # debugging switches

if is_dev_machine or debugging:   # TODO!! refactor to a separate function called by the main module

  if False:    # TODO
    np_err_default = np.geterr()
    np.seterr(all='raise')  # https://stackoverflow.com/questions/15933741/how-do-i-catch-a-numpy-warning-like-its-an-exception-not-just-for-testing
    np.seterr(under=np_err_default["under"])
    # np.seterr(divide='raise')


  if True:

    import aiodebug.log_slow_callbacks
    # import aiodebug.monitor_loop_lag

    aiodebug.log_slow_callbacks.enable(30 if is_dev_machine else 10)  # https://stackoverflow.com/questions/65704785/how-to-debug-a-stuck-asyncio-coroutine-in-python
    # aiodebug.monitor_loop_lag.enable(statsd_client) # TODO!

#/ if is_dev_machine or debugging:


if False and debugging:   # enable nested async calls so that async methods can be called from Immediate Window of Visual studio    # disabled: it is not compatible with Stampy wiki async stuff
  import nest_asyncio
  nest_asyncio.apply()


# https://stackoverflow.com/questions/28452429/does-gzip-compression-level-have-any-impact-on-decompression
# there's no extra overhead for the client/browser to decompress more heavily compressed gzip files
compresslevel = 9   # 6 is default level for gzip: https://linux.die.net/man/1/gzip
# https://github.com/ebiggers/libdeflate

data_dir = "data"



eps = 1e-15

BOM = codecs.BOM_UTF8




def set_data_dir(new_data_dir):
  global data_dir

  data_dir = new_data_dir

#/ def set_data_dir(new_data_dir):


def safeprint(text = "", is_pandas = False):

  if True or (is_dev_machine and debugging):

    screen_width = max(39, shutil.get_terminal_size((200, 50)).columns - 1)
    screen_height = max(19, shutil.get_terminal_size((200, 50)).lines - 1)

    if False:    # TODO
      np.set_printoptions(linewidth=screen_width, precision=2, floatmode="maxprec_equal", threshold=int((screen_height - 3) * screen_height / 2), edgeitems=int((screen_width - 3 - 4) / 5 / 2), formatter={ "bool": (lambda x: "T" if x else "_") }) # "maxprec_equal": Print at most precision fractional digits, but if every element in the array can be uniquely represented with an equal number of fewer digits, use that many digits for all elements.

    if is_pandas:
      import pd
      pd.set_option("display.precision", 2)
      pd.set_option("display.width", screen_width)        # pandas might fail to autodetect screen width when running under debugger
      pd.set_option("display.max_columns", screen_width)  # setting display.width is not sufficient for some  reason
      pd.set_option("display.max_rows", 100) 


  text = str(text).encode("utf-8", 'ignore').decode('ascii', 'ignore')

  if False:
    init_colors()
    print(ansi_CYAN + ansi_INTENSE + text + ansi_RESET)  # NB! need to concatenate ANSI colours not just use commas since otherwise the terminal.write would be called three times and write handler might override the colour for the text part
  else:
    print(text)

#/ def safeprint(text):


# https://stackoverflow.com/questions/5849800/tic-toc-functions-analog-in-python
class Timer(object):

  def __init__(self, name=None, quiet=False):
    self.name = name
    self.quiet = quiet

  def __enter__(self):

    if not self.quiet and self.name:
      safeprint(get_now_str() + " : " + self.name + " ...")

    self.tstart = time.time()

  def __exit__(self, type, value, traceback):

    elapsed = time.time() - self.tstart

    if not self.quiet:
      if self.name:
        safeprint(get_now_str() + " : " + self.name + " totaltime: {}".format(elapsed))
      else:
        safeprint(get_now_str() + " : " + "totaltime: {}".format(elapsed))
    #/ if not quiet:

#/ class Timer(object):


async def rename_temp_file(filename, make_backup = False):  # NB! make_backup is false by default since this operation would not be atomic

  max_tries = 20
  try_index = 1
  while True:

    try:

      if make_backup and os.path.exists(filename):

        if os.name == 'nt':   # rename is not atomic on windows and is unable to overwrite existing file. On UNIX there is no such problem
          if os.path.exists(filename + ".old"):
            if not os.path.isfile(filename + ".old"):
              raise ValueError("" + filename + ".old" + " is not a file")
            await aiofiles.os.remove(filename + ".old")

        await aiofiles.os.rename(filename, filename + ".old")

      #/ if make_backup and os.path.exists(filename):


      if os.name == 'nt':   # rename is not atomic on windows and is unable to overwrite existing file. On UNIX there is no such problem
        if os.path.exists(filename):
          if not os.path.isfile(filename):
            raise ValueError("" + filename + " is not a file")
          await aiofiles.os.remove(filename)

      await aiofiles.os.rename(filename + ".tmp", filename)

      return

    except Exception as ex:

      if try_index >= max_tries:
        raise

      try_index += 1
      safeprint("retrying temp file rename: " + filename)
      asyncio.sleep(5)
      continue

    #/ try:

  #/ while True:

#/ def rename_temp_file(filename):


def init_logging(caller_filename = "", caller_name = "", log_dir = "logs", max_old_log_rename_tries = 10):

  from Logger import Logger, rename_log_file_if_needed


  logfile_name_prefix = caller_filename + ("_" if caller_filename else "")


  full_log_dir = os.path.join(data_dir, log_dir)
  if not os.path.exists(full_log_dir):
    os.makedirs(full_log_dir)


  rename_log_file_if_needed(os.path.join(full_log_dir, logfile_name_prefix + "standard_log.txt"), max_tries = max_old_log_rename_tries)
  rename_log_file_if_needed(os.path.join(full_log_dir, logfile_name_prefix + "error_log.txt"), max_tries = max_old_log_rename_tries)
  rename_log_file_if_needed(os.path.join(full_log_dir, logfile_name_prefix + "request_log.txt"), max_tries = max_old_log_rename_tries)


  if not isinstance(sys.stdout, Logger):
    sys.stdout = Logger(sys.stdout, os.path.join(full_log_dir, logfile_name_prefix + "standard_log.txt"), False)
    if caller_name == "__main__":
      sys.stdout.write("--- Main process " + caller_filename + " ---\n")
    else:
      sys.stdout.write("--- Subprocess process " + caller_filename + " ---\n")

  if not isinstance(sys.stderr, Logger):
    sys.stderr = Logger(sys.stdout, os.path.join(full_log_dir, logfile_name_prefix + "error_log.txt"), True) # NB! redirect stderr to stdout so that error messages are saved both in standard_log as well as in error_log


  if caller_name == '__main__':
    request_logger = Logger(terminal=None, logfile=os.path.join(full_log_dir, logfile_name_prefix + "request_log.txt"), is_error_log=False)
  else:
    request_logger = None

  return request_logger

#/ def init_logging():


async def read_file(filename, default_data = {}, quiet = False):
  """Reads a pickled file"""

  fullfilename = os.path.join(data_dir, filename)

  if not os.path.exists(fullfilename + ".gz"):
    return default_data

  with Timer("file reading : " + filename, quiet):

    try:
      async with aiofiles.open(fullfilename + ".gz", 'rb', 1024 * 1024) as afh:
        compressed_data = await afh.read()    # TODO: decompress directly during reading and without using intermediate buffer for async data
        with io.BytesIO(compressed_data) as fh:   
          with gzip.open(fh, 'rb') as gzip_file:
            data = pickle.load(gzip_file)
    except FileNotFoundError:
      data = default_data

  #/ with Timer("file reading : " + filename):

  return data

#/ def read_file(filename):


async def save_file(filename, data, quiet = False, make_backup = False):
  """Writes to a pickled file"""

  haslen = hasattr(data, '__len__')
  message_template = "file saving {}" + (" num of all entries: {}" if haslen else "")
  message = message_template.format(filename, len(data) if haslen else 0)

  with Timer(message, quiet):

    fullfilename = os.path.join(data_dir, filename)

    if (1 == 1):    # enable async code

      async with aiofiles.open(fullfilename + ".gz.tmp", 'wb', 1024 * 1024) as afh:
        with io.BytesIO() as fh:    # TODO: compress directly during reading and without using intermediate buffer for async data
          with gzip.GzipFile(fileobj=fh, filename=filename, mode='wb', compresslevel=compresslevel) as gzip_file:
            pickle.dump(data, gzip_file)
            gzip_file.flush() # NB! necessary to prevent broken gz archives on random occasions (does not depend on input data)
          fh.flush()  # just in case
          buffer = bytes(fh.getbuffer())  # NB! conversion to bytes is necessary to avoid "BufferError: Existing exports of data: object cannot be re-sized"
          await afh.write(buffer)
        await afh.flush()

    else:   #/ if (1 == 0):

      with open(fullfilename + ".gz.tmp", 'wb', 1024 * 1024) as fh:
        with gzip.GzipFile(fileobj=fh, filename=filename, mode='wb', compresslevel=compresslevel) as gzip_file:
          pickle.dump(data, gzip_file)
          gzip_file.flush() # NB! necessary to prevent broken gz archives on random occasions (does not depend on input data)
        fh.flush()  # just in case

    #/ if (1 == 0):

    await rename_temp_file(fullfilename + ".gz", make_backup)

  #/ with Timer("file saving {}, num of all entries: {}".format(filename, len(cache))):

#/ def save_file(filename, data):


async def read_txt(filename, default_data = None, quiet = False):
  """Reads from a text file"""

  fullfilename = os.path.join(data_dir, filename)

  if not os.path.exists(fullfilename):
    return default_data


  message_template = "file reading {}"
  message = message_template.format(filename)

  with Timer(message, quiet):

    try:
      async with aiofiles.open(fullfilename, 'r', 1024 * 1024, encoding='utf-8') as afh:
        data = await afh.read()

    except FileNotFoundError:
      data = default_data

  #/ with Timer(message, quiet):

  return data

#/ async def read_txt(filename, quiet = False):


async def save_txt(filename, str, quiet = False, make_backup = False, append = True):
  """Writes to a text file"""

  message_template = "file saving {} num of characters: {}"
  message = message_template.format(filename, len(str))

  with Timer(message, quiet):

    fullfilename = os.path.join(data_dir, filename)

    if (1 == 1):    # enable async code

      async with aiofiles.open(fullfilename + ("" if append else ".tmp"), 'at' if append else 'wt', 1024 * 1024, encoding="utf-8") as afh:    # wt format automatically handles line breaks depending on the current OS type
        await afh.write(codecs.BOM_UTF8.decode("utf-8"))
        await afh.write(str)
        await afh.flush()

    else:   #/ if (1 == 0):

      with open(fullfilename + ("" if append else ".tmp"), 'at' if append else 'wt', 1024 * 1024, encoding="utf-8") as fh:    # wt format automatically handles line breaks depending on the current OS type
        # fh.write(codecs.BOM_UTF8 + str.encode("utf-8", "ignore"))
        fh.write(codecs.BOM_UTF8.decode("utf-8"))
        fh.write(str)
        fh.flush()  # just in case

    if not append:
      await rename_temp_file(fullfilename, make_backup)

  #/ with Timer("file saving {}, num of all entries: {}".format(filename, len(cache))):

#/ def save_txt(filename, data):


