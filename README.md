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
- Put your .csv file in the "validation_dir" directory. Update the name of the .csv file in the script file "auto_flow_script_RAG.py" accordingly.
- Run the following code.
  `python3 auto_flow_script_RAG.py`
- After a successfull run you will be able to see the results in the results directory. You will find log file for each script ran along with that script file. 

