from models import The1000GenomesMutation
from imports.mutations import MutationImporter
from imports.mutations import make_metadata_ordered_dict
from helpers.parsers import read_from_gz_files


class Importer(MutationImporter):

    model = The1000GenomesMutation
    default_path = 'data/mutations/G1000'
    insert_keys = (
        'mutation_id',
        'maf_all',
        'maf_eas',
        'maf_amr',
        'maf_afr',
        'maf_eur',
        'maf_sas',
    )

    @staticmethod
    # TODO: there are some issues with this function
    def find_af_subfield_number(line):
        """Get subfield number in 1000 Genoms VCF-originating metadata,

        where allele frequencies for given mutations are located.

        Example record:
        10	73567365	73567365	T	C	exonic	CDH23	.	nonsynonymous SNV	CDH23:NM_001171933:exon12:c.T1681C:p.F561L,CDH23:NM_001171934:exon12:c.T1681C:p.F561L,CDH23:NM_022124:exon57:c.T8401C:p.F2801L	0.001398	100	20719	10	73567365	rs3802707	TC,G	100	PASS	AC=2,5;AF=0.000399361,0.000998403;AN=5008;NS=2504;DP=20719;EAS_AF=0.001,0.005;AMR_AF=0,0;AFR_AF=0,0;EUR_AF=0,0;SAS_AF=0.001,0;AA=T|||;VT=SNP;MULTI_ALLELIC;EX_TARGET	GT
        There are AF metadata for two different mutations: T -> TC and T -> G.
        The mutation which we are currently analysing is T -> C

        Look for fields 3 and 4; 4th field is sufficient to determine mutation.
        """
        dna_mut = line[4]
        return [seq[0] for seq in line[17].split(',')].index(dna_mut)

    def parse(self, path):
        thousand_genoms_mutations = []

        maf_keys = (
            'AF',
            'EAS_AF',
            'AMR_AF',
            'AFR_AF',
            'EUR_AF',
            'SAS_AF',
        )

        for line in read_from_gz_files(
            path,
            'G1000_chr*.txt.gz',
            skip_header=False
        ):
            line = line.rstrip().split('\t')

            metadata = line[20].split(';')

            maf_data = make_metadata_ordered_dict(
                maf_keys,
                metadata,
                self.find_af_subfield_number(line)
            )

            values = list(maf_data.values())

            for mutation_id in self.preparse_mutations(line):

                thousand_genoms_mutations.append(
                    (
                        mutation_id,
                        # Python 3.5 makes it easy:
                        # **values, but is not avaialable
                        values[0],
                        values[1],
                        values[2],
                        values[3],
                        values[4],
                        values[5],
                    )
                )
        return thousand_genoms_mutations

    def insert_details(self, thousand_genoms_mutations):
        self.insert_list(thousand_genoms_mutations)
