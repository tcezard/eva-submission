#!/usr/bin/env python
import glob
import os
import shutil

from ebi_eva_common_pyutils.config import cfg
from ebi_eva_common_pyutils.logger import AppLogger

from eva_submission.eload_utils import retrieve_assembly_accession_from_ncbi, retrieve_species_names_from_tax_id
from eva_submission.submission_config import EloadConfig
from eva_submission.submission_in_ftp import FtpDepositBox
from eva_submission.xlsreader import EVAXLSReader


directory_structure = {
    'vcf': '10_submitted/vcf_files',
    'metadata': '10_submitted/metadata_file',
    'vcf_check': '13_validation/vcf_format',
    'assembly_check': '13_validation/assembly_check',
    'sample_check': '13_validation/sample_concordance',
    'biosamles': '18_brokering/biosamples',
    'ena': '18_brokering/ena',
    'scratch': '20_scratch'
}


class Eload(AppLogger):

    def __init__(self, eload_number: int):
        self.eload = f'ELOAD_{eload_number}'
        self.eload_dir = os.path.abspath(os.path.join(cfg['eloads_dir'], self.eload))
        self.eload_cfg = EloadConfig(os.path.join(self.eload_dir, '.' + self.eload + '_config.yml'))

        os.makedirs(self.eload_dir, exist_ok=True)
        for k in directory_structure:
            os.makedirs(self._get_dir(k), exist_ok=True)

    def _get_dir(self, key):
        return os.path.join(self.eload_dir, directory_structure[key])

    def copy_from_ftp(self, ftp_box, username):
        box = FtpDepositBox(ftp_box, username)

        vcf_dir = os.path.join(self.eload_dir, directory_structure['vcf'])
        for vcf_file in box.vcf_files:
            dest = os.path.join(vcf_dir, os.path.basename(vcf_file))
            shutil.copyfile(vcf_file, dest)

        if len(box.metadata_files) != 1:
            self.warning('Found %s metadata file in the FTP. Will use the most recent one', len(box.metadata_files))
        metadata_dir = os.path.join(self.eload_dir, directory_structure['metadata'])
        dest = os.path.join(metadata_dir, os.path.basename(box.most_recent_metadata))
        shutil.copyfile(box.most_recent_metadata, dest)

        for other_file in box.other_files:
            self.warning('File %s will not be treated', other_file)

    def add_to_submission_config(self, key, value):
        if 'submission' in self.eload_cfg:
            self.eload_cfg['submission'][key] = value
        else:
            self.eload_cfg['submission'] = {key: value}

    def detect_all(self):
        self.detect_submitted_metadata()
        self.detect_submitted_vcf()
        self.detect_metadata_attibutes()

    def detect_submitted_metadata(self):
        metadata_dir = os.path.join(self.eload_dir, directory_structure['metadata'])
        metadata_spreadsheets = glob.glob(os.path.join(metadata_dir, '*.xlsx'))
        if len(metadata_spreadsheets) != 1:
            raise ValueError('Found %s spreadsheet in %s', len(metadata_spreadsheets), metadata_dir)
        self.add_to_submission_config('metadata_spreadsheet', metadata_spreadsheets[0])

    def detect_submitted_vcf(self):
        vcf_dir = os.path.join(self.eload_dir, directory_structure['vcf'])
        uncompressed_vcf = glob.glob(os.path.join(vcf_dir, '*.vcf'))
        compressed_vcf = glob.glob(os.path.join(vcf_dir, '*.vcf.gz'))
        vcf_files = uncompressed_vcf + compressed_vcf
        if len(vcf_files) < 1:
            raise FileNotFoundError('Could not locate vcf file in in %s', vcf_dir)
        self.add_to_submission_config('vcf_files', vcf_files)

    def detect_metadata_attibutes(self):
        eva_metadata = EVAXLSReader(self.eload_cfg.query('submission', 'metadata_spreadsheet'))
        reference_gca = set()
        for analysis in eva_metadata.analysis:
            reference_txt = analysis.get('Reference')
            reference_gca.update(retrieve_assembly_accession_from_ncbi(reference_txt))

        if len(reference_gca) > 1:
            self.error('Multiple assemblies per project not currently supported: %s', ', '.join(reference_gca))
        elif reference_gca:
            self.add_to_submission_config('assembly_accession', reference_gca.pop())
        else:
            self.error('No genbank accession could be found for %s', reference_txt)

        taxonomy_id = eva_metadata.project.get('Tax ID')
        self.add_to_submission_config('taxonomy_id', taxonomy_id)

        retrieve_species_names_from_tax_id(taxonomy_id)
