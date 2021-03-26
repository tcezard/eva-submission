#!/usr/bin/env nextflow

def helpMessage() {
    log.info"""
    Accession variant files and copy to public FTP.

    Inputs:
            --valid_vcfs            valid vcfs to load
            --project_accession     project accession
            --instance_id           instance id to run accessioning
            --accession_job_props   job-specific properties, passed as a map
            --public_dir            directory for files to be made public
            --logs_dir              logs directory
    """
}

params.valid_vcfs = null
params.project_accession = null
params.instance_id = null
params.accession_job_props = null
params.public_dir = null
params.logs_dir = null
// executables
params.executable = ["bcftools": "bcftools", "tabix": "tabix", "copy_to_ftp": "copy_to_ftp"]
// java jars
params.jar = ["accession_pipeline": "accession_pipeline"]
// help
params.help = null

// Show help message
if (params.help) exit 0, helpMessage()

// Test input files
if (!params.valid_vcfs || !params.project_accession || !params.instance_id || !params.accession_job_props || !params.public_dir || !params.logs_dir) {
    if (!params.valid_vcfs) log.warn('Provide validated vcfs using --valid_vcfs')
    if (!params.project_accession) log.warn('Provide a project accession using --project_accession')
    if (!params.instance_id) log.warn('Provide an instance id using --instance_id')
    if (!params.accession_job_props) log.warn('Provide job-specific properties using --accession_job_props')
    if (!params.public_dir) log.warn('Provide public directory using --public_dir')
    if (!params.logs_dir) log.warn('Provide logs directory using --logs_dir')
    exit 1, helpMessage()
}

valid_vcfs = Channel.fromPath(params.valid_vcfs)


/*
 * Create properties files for accession.
 */
process create_properties {
    input:
    val vcf_file from valid_vcfs

    output:
    path "${vcf_file.getFileName()}_accessioning.properties" into accession_props
    val accessioned_filename into accessioned_filenames

    exec:
    props = new Properties()
    params.accession_job_props.each { k, v ->
        props.setProperty(k, v.toString())
    }
    props.setProperty("parameters.vcf", vcf_file.toString())
    vcf_filename = vcf_file.getFileName().toString()
    accessioned_filename = vcf_filename.take(vcf_filename.indexOf(".vcf")) + ".accessioned.vcf"
    props.setProperty("parameters.outputVcf", "${params.public_dir}/${accessioned_filename}")

    // need to explicitly store in workDir so next process can pick it up
    // see https://github.com/nextflow-io/nextflow/issues/942#issuecomment-441536175
    props_file = new File("${task.workDir}/${vcf_filename}_accessioning.properties")
    props_file.createNewFile()
    props_file.withWriter { w ->
        props.each { k, v ->
            w.write("$k=$v\n")
        }
    }
}


/*
 * Accession VCFs
 */
process accession_vcf {
    clusterOptions "-g /accession/instance-${params.instance_id}"

    memory '8 GB'

    input:
    path accession_properties from accession_props
    val accessioned_filename from accessioned_filenames

    output:
    path "${accessioned_filename}.tmp" into accession_done

    """
    filename=\$(basename $accession_properties)
    filename=\${filename%.*}
    java -Xmx7g -jar $params.jar.accession_pipeline --spring.config.name=\$filename \
        > $params.logs_dir/accessioning.\${filename}.log \
        2> $params.logs_dir/accessioning.\${filename}.err
    echo "done" > ${accessioned_filename}.tmp
    """
}


/*
 * Sort and compress accessioned VCFs
 */
process sort_and_compress_vcf {
    publishDir params.public_dir,
	mode: 'copy'

    input:
    path tmp_file from accession_done

    output:
    // used by both tabix and csi indexing processes
    path "*.gz" into compressed_vcf1, compressed_vcf2

    """
    filename=\$(basename $tmp_file)
    filename=\${filename%.*}
    $params.executable.bcftools sort -O z -o \${filename}.gz ${params.public_dir}/\${filename}
    """
}


/*
 * Index the compressed VCF file
 */
process tabix_index_vcf {
    publishDir params.public_dir,
	mode: 'copy'

    input:
    path compressed_vcf from compressed_vcf1

    output:
    path "${compressed_vcf}.tbi" into tbi_indexed_vcf

    """
    $params.executable.tabix -p vcf $compressed_vcf
    """
}


process csi_index_vcf {
    publishDir params.public_dir,
	mode: 'copy'

    input:
    path compressed_vcf from compressed_vcf2

    output:
    path "${compressed_vcf}.csi" into csi_indexed_vcf

    """
    $params.executable.bcftools index -c $compressed_vcf
    """
}


/*
 * Copy files from eva_public to FTP folder.
 */
 process copy_to_ftp {
    input:
    // ensures that all indices are done before we copy
    file csi_indices from csi_indexed_vcf.toList()
    file tbi_indices from tbi_indexed_vcf.toList()

    """
    cd $params.public_dir
    $params.executable.copy_to_ftp $params.project_accession
    """
 }