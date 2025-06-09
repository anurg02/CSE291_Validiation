# CSE291_Validiation

## Steps to install Openroad 
You can follow following docs to install OpenROAD and run ORFS flow in a docker container. 

links: 
- software guide: https://docs.google.com/document/d/1BWAddWgUqpILw1-gM8cLOaz2DBu7GkW5diUzD5C3up8/edit?usp=sharing
- ECE260C Lab0- https://docs.google.com/document/d/1UtrIMVvUHBgF3RRtPc2sWJtAfYKMoURdmns-RxxP9aY/edit?tab=t.0#heading=h.1yjqu1dwtrtc


## Steps to validate the results

### Manual Script testing 
- To be able to validate the results you have to run the script in your Docker container. (Assuming you have already installed OpenROAD and able to run ORFS.) 
- Inside the OpenROAD container's work dir, clone this repository and cd into the validation_dir directory. Create a new python file for the python script (obtained from the EDAgent).
- To run the script use following command
  
`openroad -python -exit name_of_your_script.py`

### Automated validation (Only to test the bench for EDAgent)
- To test the bench that is to test a batch of scripts generated from the EDAgent as a ".csv" file follow the following procedure. 
- There is a python script called "auto_flow_script_RAG.py" which will automate the flow to test the scripts. Put your .csv file in the "validation_dir" directory. Update the name of the .csv file in the script accordingly.
- Run the following code.
  `python3 auto_flow_script_RAG.py`
- After a successfull run you will be able to see the results in the results directory. You will find log file for each script ran along with that script file. 

### Note 
- Note that you might come across an error like this.
```
  design.getOpendp().detailedPlacement(max_disp_x, max_disp_y, "", False)
  File "dpl_py.py", line 139, in detailedPlacement
TypeError: Opendp_detailedPlacement expected at most 4 arguments, got 5
Additional information:
Wrong number or type of arguments for overloaded function 'Opendp_detailedPlacement'.
```
- Note that this error exists because of a minor change in API used by our OpenROAD version and the OpenROAD version assumed by the EDA corpus scripts.
- This is an accepted error if the script fails to run #only because of this we can still consider this as a success.
- If you want to test the full run of the script. Make following changes to the API call.
  '''
  design.getOpendp().detailedPlacement(max_disp_x, max_disp_y, "") // don't pass the last argument.
  '''
  

  
