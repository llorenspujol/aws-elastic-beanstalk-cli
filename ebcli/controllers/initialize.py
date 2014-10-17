# Copyright 2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.

from ..core.abstractcontroller import AbstractBaseController
from ..resources.strings import strings
from ..core import fileoperations, io, operations
from ..objects.exceptions import NotInitializedError, NoRegionError, \
    InvalidProfileError
from ..objects import region as regions
from ..lib import utils, elasticbeanstalk, aws


class InitController(AbstractBaseController):
    class Meta:
        label = 'init'
        help = 'blarg!!'
        description = strings['init.info']
        arguments = [
            (['application_name'], dict(help='Application name',
                                        nargs='?', default=[])),
            (['-r', '--region'], dict(help='Default Region')),
            (['-s', '--solution'], dict(help='Default Solution stack')),
            (['-k', '--keyname'], dict(help='Default EC2 key name')),
            (['-i', '--interactive'], dict(action='store_true',
                                           help='Force interactive mode')),
            (['--nossh'], dict(action='store_true',
                               help='Dont  setup ssh'))
        ]
        usage = 'eb init <application_name> [options ...]'
        epilog = strings['init.epilog']

    def do_command(self):
        # get arguments
        self.nossh = self.app.pargs.nossh
        self.interactive = self.app.pargs.interactive
        self.region = self.app.pargs.region
        self.flag = False
        if self.app.pargs.application_name and self.app.pargs.solution:
            self.flag = True

        default_env = self.get_old_values()
        fileoperations.touch_config_folder()

        if self.interactive:
            self.region = self.get_region()

        self.set_up_credentials()

        self.solution = self.get_solution_stack()
        self.app_name = self.get_app_name()

        if not default_env:
            # try to get default env from config file if exists
            try:
                default_env = operations.get_current_branch_environment()
            except NotInitializedError:
                default_env = None

        # Create application
        sstack, key = operations.create_app(self.app_name, self.region,
                                            default_env=default_env)

        if not self.solution:
            self.solution = sstack

        if not self.solution or self.interactive:
            result = operations.prompt_for_solution_stack(self.region)
            self.solution = result.version

        self.keyname = self.get_keyname(default=key)

        operations.setup(self.app_name, self.region, self.solution,
                         self.keyname)

    def check_credentials(self, profile):
        given_profile = self.app.pargs.profile
        try:
            # Note, region is None unless explicitly set
            ## or read from old eb
            operations.credentials_are_valid(self.region)
        except NoRegionError:
            self.region = self.get_region()
        except InvalidProfileError:
            if given_profile:
                # Provided profile is invalid, raise exception
                raise
            else:
                # eb-cli profile doesnt exist, revert to default
                # try again
                profile = None
                aws.set_profile(profile)
                self.check_credentials(profile)

    def set_up_credentials(self):
        given_profile = self.app.pargs.profile
        if given_profile:
            ## Profile already set at abstractController
            profile = given_profile
        else:
            profile = 'eb-cli'
            aws.set_profile(profile)

        self.check_credentials(profile)

        if not operations.credentials_are_valid(self.region):
            operations.setup_credentials()
        elif given_profile:
            fileoperations.write_config_setting('global', 'profile',
                                                profile)

    def get_app_name(self):
        # Get app name from command line arguments
        app_name = self.app.pargs.application_name

        # Get app name from config file, if exists
        if not app_name:
            try:
                app_name = fileoperations.get_application_name(default=None)
            except NotInitializedError:
                app_name = None

        # Ask for app name
        if not app_name or self.interactive:
            app_name = _get_application_name_interactive(self.region)

        return app_name

    def get_region(self):
        # Get region from command line arguments
        region = self.app.pargs.region

        # Get region from config file
        if not region:
            try:
                region = fileoperations.get_default_region()
            except NotInitializedError:
                region = None

        # Ask for region
        if not region or self.interactive:
            io.echo()
            io.echo('Select a default region')
            region_list = regions.get_all_regions()
            result = utils.prompt_for_item_in_list(region_list, default=3)
            region = result.name

        return region

    def get_solution_stack(self):
        # Get solution stack from command line arguments
        solution_string = self.app.pargs.solution

        # Get solution stack from config file, if exists
        if not solution_string:
            try:
                solution_string = fileoperations.get_default_solution_stack()
            except NotInitializedError:
                solution_string = None

        if solution_string:
            operations.get_solution_stack(solution_string, self.region)

        return solution_string

    def get_keyname(self, default=None):
        if self.nossh:
            return None

        keyname = self.app.pargs.keyname

        if not keyname:
            keyname = default

        # Get keyname from config file, if exists
        if not keyname:
            try:
                keyname = fileoperations.get_default_keyname()
            except NotInitializedError:
                keyname = None

        if self.flag and not self.interactive:
            return keyname

        if not keyname or self.interactive:
            # Prompt for one
            keyname = operations.prompt_for_ec2_keyname(self.region)

        return keyname

    def complete_command(self, commands):
        self.complete_region(commands)
        #Note, completing solution stacks is only going to work
        ## if they already have their keys set up with region
        if commands[-1] in ['-s', '--solution']:
            io.echo(*elasticbeanstalk.get_available_solution_stacks())

    def get_old_values(self):
        if fileoperations.old_eb_config_present():
            old_values = fileoperations.get_values_from_old_eb()
            region = old_values['region']
            access_id = old_values['access_id']
            secret_key = old_values['secret_key']
            solution_stack = old_values['solution_stack_name']
            app_name = old_values['app_name']
            default_env = old_values['default_env']

            io.echo(strings['init.getvarsfromoldeb'])
            if self.region is None:
                self.region = region
            if not self.app.pargs.application_name:
                self.app.pargs.application_name = app_name
            if self.app.pargs.solution is None:
                self.app.pargs.solution = solution_stack

            operations.setup_credentials(access_id=access_id,
                                         secret_key=secret_key)
            return default_env

        return None


def _get_application_name_interactive(region):
    app_list = operations.get_application_names(region)
    file_name = fileoperations.get_current_directory_name()
    new_app = False
    if len(app_list) > 0:
        io.echo()
        io.echo('Select an application to use')
        new_app_option = '[ Create new Application ]'
        app_list.append(new_app_option)
        try:
            default_option = app_list.index(file_name) + 1
        except ValueError:
            default_option = len(app_list)
        app_name = utils.prompt_for_item_in_list(app_list,
                                                 default=default_option)
        if app_name == new_app_option:
            new_app = True

    if len(app_list) == 0 or new_app:
        io.echo()
        io.echo('Enter Application Name')
        unique_name = utils.get_unique_name(file_name, app_list)
        app_name = io.prompt_for_unique_name(unique_name, app_list)

    return app_name