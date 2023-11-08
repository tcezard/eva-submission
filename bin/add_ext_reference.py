#!/usr/bin/env python

# Copyright 2020 EMBL - European Bioinformatics Institute
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import logging
import sys

import requests
from ebi_eva_common_pyutils.config import cfg
from ebi_eva_common_pyutils.logger import logging_config as log_cfg
from ebi_eva_internal_pyutils.metadata_utils import get_metadata_connection_handle
from ebi_eva_internal_pyutils.pg_utils import get_all_results_for_query, execute_query
from retry import retry

from eva_submission.eload_utils import check_project_exists_in_evapro, check_existing_project_in_ena
from eva_submission.submission_config import load_config

logger = log_cfg.get_logger(__name__)


def add_external_reference_to_ena(project_accession, source_database, identifier):
    logger.warning('This script does not support uploading the external reference to ENA. Please do this manually')


class EvaproExtReference:

    @property
    def metadata_connection_handle(self):
        return get_metadata_connection_handle(cfg['maven']['environment'], cfg['maven']['settings_file'])

    def _get_dbxref_id(self, source_database, identifier):
        # get the dbxref_id that was autogenerated in the row that we just inserted in dbxref
        with self.metadata_connection_handle as conn:
            query = f"SELECT dbxref_id FROM evapro.dbxref WHERE db='{source_database}' and id='{identifier}'"
            res = list(get_all_results_for_query(conn, query))
            if res:
                return res[0][0]

    def _get_project_dbxref_id(self, project_accession, dbxref_id):
        with self.metadata_connection_handle as conn:
            query = f"SELECT dbxref_id FROM evapro.project_dbxref " \
                    f"WHERE project_accession='{project_accession}' and dbxref_id='{dbxref_id}'"
            res = list(get_all_results_for_query(conn, query))
            if res:
                return res[0]

    def add_external_reference_to_evapro(self, project_accession, source_database, identifier):
        dbxref_id = self._get_dbxref_id(source_database, identifier)
        if not dbxref_id:
            query = f"INSERT into evapro.dbxref (db, id, link_type, source_object) " \
                    f"VALUES ('{source_database}', '{identifier}', 'publication', 'project')"
            with self.metadata_connection_handle as conn:
                execute_query(conn, query)
            dbxref_id = self._get_dbxref_id(source_database, identifier)
        assert dbxref_id, f"Failed to create the entry for {source_database}:{identifier}"
        if not self._get_project_dbxref_id(project_accession, dbxref_id):
            query = f"INSERT into project_dbxref (project_accession, dbxref_id) " \
                    f"VALUES ('{project_accession}', '{dbxref_id}')"
            with self.metadata_connection_handle as conn:
                execute_query(conn, query)


@retry(tries=3, delay=2, backoff=1.2, jitter=(1, 3))
def _curie_exist(curie):
    response = requests.get('https://resolver.api.identifiers.org/' + curie)
    json_data = response.json()
    resources = json_data["payload"]["resolvedResources"]
    for resource in resources:
        response = requests.head(resource['compactIdentifierResolvedUrl'])
        if response.ok:
            return True
        else:
            logger.warning(f'Cannot resolve {curie} in {resource["description"]}')
    return False


def main():
    arg_parser = argparse.ArgumentParser(description='Add an external reference to the project specified')
    arg_parser.add_argument('--project_accession', type=str, required=True,
                            help='The project associated with the external reference.')
    arg_parser.add_argument('--source_database', required=True, default='PubMed',
                            help='The database the external reference relates to')

    arg_parser.add_argument('--identifier', required=True, help='The identifier of the external reference')
    arg_parser.add_argument('--debug', action='store_true', default=False,
                            help='Set the script to output logging information at debug level')
    args = arg_parser.parse_args()

    log_cfg.add_stdout_handler()

    if args.debug:
        log_cfg.set_log_level(logging.DEBUG)

    # Load the config_file from default location
    load_config()

    if not check_project_exists_in_evapro(args.project_accession):
        logger.error(f'{args.project_accession} does not exist in EVAPRO')
        return 1
    if not check_existing_project_in_ena(args.project_accession):
        logger.error(f'{args.project_accession} does not exist or is not public in ENA')
        return 1
    if _curie_exist(args.source_database + ":" + args.identifier):
        add_external_reference_to_ena(args.project_accession, args.source_database, args.identifier)
        EvaproExtReference().add_external_reference_to_evapro(args.project_accession, args.source_database, args.identifier)
    else:
        logger.error(f'Cannot resolve {args.source_database}:{args.identifier} in identifiers.org')

    return 0


if __name__ == "__main__":
    sys.exit(main())