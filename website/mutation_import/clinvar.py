from models import InheritedMutation
from models import ClinicalData
from import_mutations import MutationImporter
from import_mutations import make_metadata_ordered_dict
from import_mutations import bulk_ORM_insert
from helpers.parsers import parse_tsv_file


class Importer(MutationImporter):

    model = InheritedMutation
    default_path = 'data/mutations/clinvar_muts_annotated.txt'
    insert_keys = (
        'mutation_id',
        'db_snp_id',
        'is_low_freq_variation',
        'is_validated',
        'is_in_pubmed_central',
    )

    @staticmethod
    def _beautify_disease_name(name):
        return name.replace('\\x2c', ',').replace('_', ' ')

    def parse(self, path):
        clinvar_mutations = []
        clinvar_data = []

        clinvar_keys = (
            'RS',
            'MUT',
            'VLD',
            'PMC',
            'CLNSIG',
            'CLNDBN',
            'CLNREVSTAT',
        )

        def clinvar_parser(line):

            metadata = line[20].split(';')

            clinvar_entry = make_metadata_ordered_dict(clinvar_keys, metadata)

            names, statuses, significances = (
                (entry.replace('|', ',').split(',') if entry else None)
                for entry in
                (
                    clinvar_entry[key]
                    for key in ('CLNDBN', 'CLNREVSTAT', 'CLNSIG')
                )
            )

            # those length should be always equal if they exists
            sub_entries_cnt = max(
                [
                    len(x)
                    for x in (names, statuses, significances)
                    if x
                ] or [0]
            )

            for i in range(sub_entries_cnt):

                try:
                    if names:
                        if names[i] == 'not_specified':
                            names[i] = None
                        else:
                            names[i] = self._beautify_disease_name(names[i])
                    if statuses and statuses[i] == 'no_criteria':
                        statuses[i] = None
                except IndexError:
                    print('Malformed row (wrong count of subentries):')
                    print(line)
                    return False

            values = list(clinvar_entry.values())

            for mutation_id in self.preparse_mutations(line):

                # Python 3.5 makes it easy: **values (but is not avaialable)
                clinvar_mutations.append(
                    (
                        mutation_id,
                        values[0],
                        values[1],
                        values[2],
                        values[3],
                    )
                )

                for i in range(sub_entries_cnt):
                    clinvar_data.append(
                        (
                            len(clinvar_mutations),
                            significances[i] if significances else None,
                            names[i] if names else None,
                            statuses[i] if statuses else None,
                        )
                    )

        parse_tsv_file(path, clinvar_parser)

        return clinvar_mutations, clinvar_data

    def insert_details(self, details):
        clinvar_mutations, clinvar_data = details
        self.insert_list(clinvar_mutations)

        bulk_ORM_insert(
            ClinicalData,
            (
                'inherited_id',
                'sig_code',
                'disease_name',
                'rev_status',
            ),
            clinvar_data
        )