# Copyright (c) 2017 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import os
import sys
import shutil
import zipfile
import tempfile
from shutil import copy
from urlparse import urlparse

import requests

from cloudify import ctx
from cloudify.exceptions import NonRecoverableError
from cloudify.exceptions import OperationRetry
from cloudify.utils import exception_to_error_cause


def generate_traceback_exception():
    _, exc_value, exc_traceback = sys.exc_info()
    response = exception_to_error_cause(exc_value, exc_traceback)
    return response


def get_desired_value(key,
                      args,
                      instance_attr,
                      node_prop):

    return (args.get(key) or
            instance_attr.get(key) or
            node_prop.get(key))


def update_attributes(_type, _key, _value):
    ctx.instance.runtime_properties[_type][_key] = _value


def proxy_operation(operation):
    def decorator(task, **kwargs):
        def wrapper(**kwargs):
            try:
                kwargs['operation'] = operation
                return task(**kwargs)
            except OperationRetry:
                response = generate_traceback_exception()

                ctx.logger.error(
                    'Error traceback {0} with message {1}'.format(
                        response['traceback'], response['message']))

                raise OperationRetry(
                    'Error: {0} while trying to run proxy task {1}'
                    ''.format(response['message'], operation))

            except Exception:
                response = generate_traceback_exception()

                ctx.logger.error(
                    'Error traceback {0} with message {1}'.format(
                        response['traceback'], response['message']))

                raise NonRecoverableError(
                    'Error: {0} while trying to run proxy task {1}'
                    ''.format(response['message'], operation))

        return wrapper
    return decorator


def download_file(url, destination=None, keep_name=False):
    """Download file.

    :param url: Location of the file to download
    :type url: str
    :param destination:
        Location where the file should be saved (autogenerated by default)
    :param keep_name: use the filename from the url as destination filename
    :type destination: str | None
    :returns: Location where the file was saved
    :rtype: str

    """
    CHUNK_SIZE = 1024

    if not destination:
        if keep_name:
            path = urlparse(url).path
            name = os.path.basename(path)
            destination = os.path.join(tempfile.mkdtemp(), name)
        else:
            fd, destination = tempfile.mkstemp()
            os.close(fd)

    ctx.logger.info('Downloading {0} to {1}...'.format(url, destination))

    try:
        response = requests.get(url, stream=True)
    except requests.exceptions.RequestException as ex:
        raise NonRecoverableError(
            'Failed to download {0}. ({1})'.format(url, str(ex)))

    final_url = response.url
    if final_url != url:
        ctx.logger.debug('Redirected to {0}'.format(final_url))

    try:
        with open(destination, 'wb') as destination_file:
            for chunk in response.iter_content(CHUNK_SIZE):
                destination_file.write(chunk)
    except IOError as ex:
        raise NonRecoverableError(
            'Failed to download {0}. ({1})'.format(url, str(ex)))

    return destination


def get_local_path(source, destination=None, create_temp=False):
    allowed_schemes = ['http', 'https']
    if urlparse(source).scheme in allowed_schemes:
        downloaded_file = download_file(source, destination, keep_name=True)
        return downloaded_file
    elif os.path.isfile(source):
        if not destination and create_temp:
            source_name = os.path.basename(source)
            destination = os.path.join(tempfile.mkdtemp(), source_name)
        if destination:
            shutil.copy(source, destination)
            return destination
        else:
            return source
    else:
        raise NonRecoverableError(
            'You must provide either a path to a local file, or a remote URL '
            'using one of the allowed schemes: {0}'.format(allowed_schemes))


def zip(source, destination, include_folder=True):
    ctx.logger.debug('Creating zip archive: {0}...'.format(destination))
    with zipfile.ZipFile(destination, 'w') as zip_file:
        for root, _, files in os.walk(source):
            for filename in files:
                file_path = os.path.join(root, filename)
                source_dir = os.path.dirname(source) if include_folder\
                    else source
                zip_file.write(
                    file_path, os.path.relpath(file_path, source_dir))
    return destination


def zip_files(files):
    source_folder = tempfile.mkdtemp()
    destination_zip = source_folder + '.zip'
    for path in files:
        copy(path, source_folder)
    zip(source_folder, destination_zip, include_folder=False)
    shutil.rmtree(source_folder)
    return destination_zip
