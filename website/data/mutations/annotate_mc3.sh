#!/bin/bash
if [ -f annovar.latest.tar.gz ];
then
    tar -xvzf annovar.latest.tar.gz
    rm annovar.latest.tar.gz
else
    if [ ! -d annovar ];
    then
        echo "Please, download annovar into data/mutations directory and run data/mutations/annotate_mc3.sh script then"
        exit 1
    fi
fi

if [ ! -d humandb ];
then
    ./annovar/annotate_variation.pl -buildver hg19 -downdb -webfrom annovar refGene humandb/
fi

file=mc3.v0.2.8.PUBLIC.maf.gz   

# get all columns required for annovar, skipping header line (first row)
zcat $file | tail -n +2 | cut -f 5,6,7,11,47 > mc3.avinput
# reannotate all mutations on GRCh37/hg19
./annovar/table_annovar.pl mc3.avinput humandb/ -buildver hg19 -out mc3_annotated -remove -protocol refGene -operation g -nastring . -thread 2
# add barcodes as comments; keep only those which are nonsynonymous SNVs
paste <(cat mc3_annotated.hg19_multianno.txt) <(zcat $file  | cut -f 16) | awk -F '\t' '$9 ~ /nonsynonymous SNV/' | gzip > mc3_muts_annotated.txt.gz

rm mc3.avinput
