import errno
import os
import socket
import subprocess
import tempfile
import time
from collections import namedtuple

# External modules
import paramiko

# Flintrock modules
from .exceptions import SSHError


def generate_ssh_key_pair() -> namedtuple('KeyPair', ['public', 'private']):
    """
    Generate an SSH key pair that the cluster can use for intra-cluster
    communication.
    """
    with tempfile.TemporaryDirectory() as tempdir:
        subprocess.check_call([
            'ssh-keygen',
            '-q',
            '-t', 'rsa',
            '-N', '',
            '-f', os.path.join(tempdir, 'flintrock_rsa'),
            '-C', 'flintrock'])

        with open(file=os.path.join(tempdir, 'flintrock_rsa')) as private_key_file:
            private_key = private_key_file.read()

        with open(file=os.path.join(tempdir, 'flintrock_rsa.pub')) as public_key_file:
            public_key = public_key_file.read()

    return namedtuple('KeyPair', ['public', 'private'])(public_key, private_key)


def get_ssh_client(
        *,
        user: str,
        host: str,
        identity_file: str,
        wait: bool=False,
        print_status: bool=None) -> paramiko.client.SSHClient:
    """
    Get an SSH client for the provided host, waiting as necessary for SSH to become
    available.
    """
    if print_status is None:
        print_status = wait

    client = paramiko.client.SSHClient()

    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.client.AutoAddPolicy())

    if wait:
        tries = 100
    else:
        tries = 1

    while tries > 0:
        try:
            tries -= 1
            client.connect(
                username=user,
                hostname=host,
                key_filename=identity_file,
                look_for_keys=False,
                timeout=3)
            if print_status:
                print("[{h}] SSH online.".format(h=host))
            break
        except socket.timeout as e:
            time.sleep(5)
        except socket.error as e:
            if e.errno != errno.ECONNREFUSED:
                raise
            time.sleep(5)
        # We get this exception during startup with CentOS but not Amazon Linux,
        # for some reason.
        except paramiko.ssh_exception.AuthenticationException as e:
            time.sleep(5)
    else:
        raise SSHError(
            host=host,
            message="Could not connect via SSH.")

    return client


def ssh_check_output(client: paramiko.client.SSHClient, command: str):
    """
    Run a command via the provided SSH client and return the output captured
    on stdout.

    Raise an exception if the command returns a non-zero code.
    """
    stdin, stdout, stderr = client.exec_command(command, get_pty=True)

    # NOTE: Paramiko doesn't clearly document this, but we must read() before
    #       calling recv_exit_status().
    #       See: https://github.com/paramiko/paramiko/issues/448#issuecomment-159481997
    stdout_output = stdout.read().decode('utf8').rstrip('\n')
    stderr_output = stderr.read().decode('utf8').rstrip('\n')
    exit_status = stdout.channel.recv_exit_status()

    if exit_status:
        # TODO: Return a custom exception that includes the return code.
        #       See: https://docs.python.org/3/library/subprocess.html#subprocess.check_output
        # NOTE: We are losing the output order here since output from stdout and stderr
        #       may be interleaved.
        raise SSHError(
            host=client.get_transport().getpeername()[0],
            message=stdout_output + stderr_output)

    return stdout_output


def ssh(*, user: str, host: str, identity_file: str):
    """
    SSH into a host for interactive use.
    """
    ret = subprocess.call([
        'ssh',
        '-o', 'StrictHostKeyChecking=no',
        '-i', identity_file,
        '{u}@{h}'.format(u=user, h=host)])
