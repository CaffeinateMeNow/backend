import multiprocessing
import os
import subprocess
import tempfile
import time

import pytest

from mediawords.util.process import (process_with_pid_is_running, run_command_in_foreground,
                                     run_alone, gracefully_kill_child_process,
                                     McRunCommandInForegroundException,
                                     McScriptInstanceIsAlreadyRunning, log)


def test_process_with_pid_is_running():
    test_process = subprocess.Popen(['sleep', '999'])
    test_process_pid = test_process.pid

    assert test_process_pid != 0
    assert test_process_pid is not None

    assert process_with_pid_is_running(test_process_pid) is True

    # again to test if os.kill() just tests the process, not actually kills it
    assert process_with_pid_is_running(test_process_pid) is True

    test_process.terminate()
    test_process.kill()

    test_process.communicate()
    assert process_with_pid_is_running(test_process_pid) is False


def test_run_command_in_foreground():
    temp_dir = tempfile.mkdtemp()

    test_file_to_create = os.path.join(temp_dir, 'test.txt')
    assert os.path.isfile(test_file_to_create) is False

    run_command_in_foreground(['touch', test_file_to_create])
    assert os.path.isfile(test_file_to_create) is True

    run_command_in_foreground(['rm', test_file_to_create])
    assert os.path.isfile(test_file_to_create) is False

    # Environment variables
    test_env_variable = 'MC_RUN_COMMAND_IN_FOREGROUND_ENV_TEST'
    test_file_with_env = os.path.join(temp_dir, 'env.txt')
    test_file_without_env = os.path.join(temp_dir, 'no-env.txt')
    run_command_in_foreground(['/bin/bash', '-c', 'env > %s' % test_file_with_env],
                              env={test_env_variable: '1'})
    run_command_in_foreground(['/bin/bash', '-c', 'env > %s' % test_file_without_env], env={})
    with open(test_file_with_env, 'r') as f:
        contents = f.read()
        assert test_env_variable in contents
    with open(test_file_without_env, 'r') as f:
        contents = f.read()
        assert test_env_variable not in contents

    # cwd
    test_file_with_cwd = os.path.join(temp_dir, 'cwd.txt')
    test_file_without_cwd = os.path.join(temp_dir, 'no-cwd.txt')
    run_command_in_foreground(['/bin/bash', '-c', 'pwd > %s' % test_file_with_cwd], cwd=temp_dir)
    run_command_in_foreground(['/bin/bash', '-c', 'pwd > %s' % test_file_without_cwd])
    with open(test_file_with_cwd, 'r') as f:
        contents = f.read()
        assert temp_dir in contents
    with open(test_file_without_cwd, 'r') as f:
        contents = f.read()
        assert temp_dir not in contents

    # Faulty command
    with pytest.raises(McRunCommandInForegroundException):
        run_command_in_foreground(['this_command_totally_doesnt_exist'])


def test_gracefully_kill_child_process():
    test_process = subprocess.Popen(['sleep', '999'])
    test_process_pid = test_process.pid

    assert test_process_pid != 0
    assert test_process_pid is not None

    assert process_with_pid_is_running(test_process_pid) is True

    gracefully_kill_child_process(child_pid=test_process_pid, sigkill_timeout=3)

    test_process.communicate()
    assert process_with_pid_is_running(test_process_pid) is False


def test_run_alone():
    # Basic usage
    def create_file(file_to_create, sleep_forever_afterwards):
        if os.path.exists(file_to_create):
            raise Exception("File '%s' already exists." % file_to_create)
        file = open(file_to_create, 'w+')
        file.write('Foo.')
        file.close()

        if sleep_forever_afterwards:
            log.info("PID %d sleeping forever" % os.getpid())
            while True:
                time.sleep(1)
        else:
            return True

    temp_file = os.path.join(tempfile.mkdtemp(), 'foo.dat')
    assert not os.path.exists(temp_file)

    return_value = run_alone(create_file, temp_file, False)
    assert return_value is True
    assert os.path.exists(temp_file)

    # Make sure that two instances of a function can't be run alone
    background_thread_temp_file = os.path.join(tempfile.mkdtemp(), 'background_thread.dat')
    assert not os.path.exists(background_thread_temp_file)

    background_thread = multiprocessing.Process(
        name='background_thread',
        target=run_alone,
        args=(create_file, background_thread_temp_file, True,)
    )
    background_thread.daemon = True
    background_thread.start()
    time.sleep(1)

    # Make sure background thread is started
    assert os.path.exists(background_thread_temp_file)

    # Try running same function in foreground thread, make sure it fails
    foreground_thread_temp_file = os.path.join(tempfile.mkdtemp(), 'foreground_thread.dat')
    assert not os.path.exists(foreground_thread_temp_file)
    with pytest.raises(McScriptInstanceIsAlreadyRunning):
        run_alone(create_file, foreground_thread_temp_file, True)

    assert not os.path.exists(foreground_thread_temp_file)

    # FIXME doesn't get properly killed it seems
    os.system('kill -INT {}'.format(background_thread.pid))
    background_thread.terminate()
    background_thread.join(timeout=2)

    # Try running function again to make sure that the lock file got removed properly
    another_foreground_thread_temp_file = os.path.join(tempfile.mkdtemp(),
                                                       'another_foreground_thread.dat')
    assert not os.path.exists(another_foreground_thread_temp_file)

    run_alone(create_file, another_foreground_thread_temp_file, False)
    assert os.path.exists(another_foreground_thread_temp_file)
