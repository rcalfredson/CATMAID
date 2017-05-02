# -*- coding: utf-8 -*-
from __future__ import unicode_literals

# This is a hack to disable GDAL support in GeoDjango. It seems there is no
# easier way due to the GDAL_LIBRARY_PATH setting not behaving as documented
# (i.e. setting it to a non-existent file will disable GDAL). Disabling GDAL is
# unfortunately needed, because it breaks TIFF support for pgmagick, which is
# required by e.g. the cropping back-end. GeoDjango loads GDAL into memory
# which a) is a waste of memory if we don't use it and b) on at least Ubuntu
# GDAL seems to be compiled in a way that it takes over TIFF I/O. And this
# causes pgmagick to segfault. This patch is added here, because the database
# engine is the first thing that is loaded which loads GeoDjango's GDAL module.
# The patch below is based on the GeoDjango's GDAL module for Django 1.10:
# https://github.com/django/django/blob/stable/1.10.x/django/contrib/gis/gdal/libgdal.py

import logging
import os
import sys

original_os_name = os.name
os.name = "GDAL blocking OS"
from django.contrib.gis import gdal
os.name = original_os_name
if not gdal.HAS_GDAL:
    logging.warn("GeoDjango's GDAL support was disabled by "
           "CATMAID, because it breaks TIFF support in pgmagick. See "
           "https://github.com/catmaid/CATMAID/issues/1218 for more details.")

# Unfortunately, we also need to mock the GDALRaster class, see
# https://code.djangoproject.com/ticket/28160 for details
import django.contrib.gis.gdal
class GDALRasterMock(object):
    pass
django.contrib.gis.gdal.GDALRaster = GDALRasterMock
