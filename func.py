############################################################################
#   This functions retrieves instance display_name                         # 
#   then applies a freeform_tag: key=display_name value=inst_display_name  #	
#   when 'Instance - Launch End': tag instance + boot volume               #
#   when 'Volume - Attach End': tag attached volume                        #
#                                                                          #
#   no need to tag boot/block volumes backups because they automatically   #
#   apply same tags as their parent boot/block volumes                     #
#                                                                          #
#   OCI-FN_TagCompute_FF.py                                                #
#   Florian Bonneville                                                     #
#   2023-03-13                                                             #
#   1.0.0                                                                  #
############################################################################

import io
import json
import oci
import logging
from fdk import response

# Lower debug logging
logging.getLogger('oci').setLevel(logging.INFO)
logging.getLogger("oci._vendor.urllib3.connectionpool").setLevel(logging.INFO)

#========================================================================
# configure this section using your own Tagkey value
#========================================================================

TagKey = 'display_name'

##########################################################################
# get boot volume instance
##########################################################################

def list_instances_bootvol(core_client, availability_domain, compartment_id, instance_id):
    
    my_bootvol=[]
    boot_volumes=oci.pagination.list_call_get_all_results(core_client.list_boot_volume_attachments,availability_domain=availability_domain, compartment_id=compartment_id, instance_id=instance_id).data
    for bootvol in boot_volumes:
        my_bootvol.append(bootvol)

    return my_bootvol

##########################################################################
# list all block volume attached to this instance
##########################################################################

def list_instances_volattach(core_client, availability_domain, compartment_id, instance_id):

    volattachs=oci.pagination.list_call_get_all_results(core_client.list_volume_attachments,availability_domain=availability_domain, compartment_id=compartment_id, instance_id=instance_id).data
    my_blk_attach=[]

    for volattach in volattachs:
        my_blk_attach.append(volattach)
    return my_blk_attach

##########################################################################
# tag associated resources
##########################################################################

def tag_resources(type, oci_client, resource_id, freeform_tags_dict):
    
    if type == 'instance':
        details = oci.core.models.UpdateInstanceDetails(freeform_tags=freeform_tags_dict)
        response = oci_client.update_instance(resource_id,details)

    if type == 'boot_volume':
        try:
            details = oci.core.models.UpdateBootVolumeDetails(freeform_tags={})
            response = oci_client.update_boot_volume(resource_id,details)
        except:
            pass
        details = oci.core.models.UpdateBootVolumeDetails(freeform_tags=freeform_tags_dict)
        response = oci_client.update_boot_volume(resource_id,details)
        
    if type == 'block_volume':
        try:
            details = oci.core.models.UpdateVolumeDetails(freeform_tags={})
            response = oci_client.update_volume(resource_id,details)
        except:
            pass
        details = oci.core.models.UpdateVolumeDetails(freeform_tags=freeform_tags_dict)
        response = oci_client.update_volume(resource_id,details)

    return response

##########################################################################
# main
##########################################################################

def handler(ctx, data: io.BytesIO=None):
    signer = oci.auth.signers.get_resource_principals_signer()
    core_client = oci.core.ComputeClient(config={}, signer=signer)
    blk_storage_client=oci.core.BlockstorageClient(config={}, signer=signer)

    try:
        body=json.loads(data.getvalue())
        resource_data = body["data"]
        #print(f"F.log: res_data: {resource_data}", flush=True)

        resource_comp_id = body["data"]["compartmentId"]
        #print(f"F.log: res.comp_id:{resource_comp_id}", flush=True)

        resource_comp_name = body["data"]["compartmentName"]
        #print(f"F.log: res.name:{resource_comp_name}", flush=True)

        resource_ocid = body["data"]["resourceId"]
        #print(f"F.log: res.id: {resource_ocid}", flush=True)

        ##########################################################################
        #  when function receives 'Instance - Launch End' notification: 
        # it tags both instance and attached block volume
        ##########################################################################
        if 'ocid1.instance.' in resource_ocid:
            try:
                instance = core_client.get_instance(resource_ocid).data

                # retrieve instance tags
                freeform_tags_dict = instance.freeform_tags
                # add key/value to dict
                freeform_tags_dict[TagKey] = instance.display_name
                print(f"F.log: Tagging instance: {instance.display_name}", flush=True)
                tag_resources('instance', core_client, instance.id, freeform_tags_dict)

                ##########################################################################
                # searchs and tags attached boot volume
                ##########################################################################           
                instance_bootvolattach=list_instances_bootvol(core_client, instance.availability_domain, instance.compartment_id, instance.id)

                for bootvolattach in instance_bootvolattach:
                    bootvol=blk_storage_client.get_boot_volume(bootvolattach.boot_volume_id).data

                    # retrieve boot volume tags
                    freeform_tags_dict = bootvol.freeform_tags
                    # add key/value to dict
                    freeform_tags_dict[TagKey] = instance.display_name
                    print(f"F.log: Tagging boot volume: {bootvol.display_name}", flush=True)
                    tag_resources('boot_volume', blk_storage_client, bootvol.id, freeform_tags_dict)

                print(f"F.log: Compartment: {resource_comp_name}", flush=True)

            except Exception as e:
                print(e)

        ##########################################################################
        # when function receives 'Volume - Attach End' notification:
        # it tags attached block volumes
        ##########################################################################

        if 'ocid1.volumeattachment.' in resource_ocid:
            volume_attachment=core_client.get_volume_attachment(resource_ocid).data

            try:
                instance_vol_attach=list_instances_volattach(core_client, volume_attachment.availability_domain, resource_comp_id, volume_attachment.instance_id)

                for vol_attach in instance_vol_attach:
                    volume=blk_storage_client.get_volume(vol_attach.volume_id).data
                    instance_display_name = core_client.get_instance(volume_attachment.instance_id).data.display_name

                    # retrieve volume tags
                    freeform_tags_dict = volume.freeform_tags
                    # add key/value to dict
                    freeform_tags_dict[TagKey] = instance_display_name
                    print(f"F.log: Tagging Volume: {volume.display_name}", flush=True)
                    tag_resources('block_volume', blk_storage_client, volume.id, freeform_tags_dict)
                
                print(f"F.log: Compartment: {resource_comp_name}", flush=True)

            except Exception as e:
                print(e)

    except (Exception) as ex:
        print('handler failed: {0}'.format(ex), flush=True)
        raise

    return response.Response(
        ctx,
        response_data=json.dumps(body),
        headers={"Content-Type": "application/json"}
    )