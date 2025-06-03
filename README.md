# CSE291_Validiation

## Steps to install Openroad 
You can follow following docs to install OpenROAD and run ORFS flow in a docker container. 

links: 
- software guide: https://docs.google.com/document/d/1BWAddWgUqpILw1-gM8cLOaz2DBu7GkW5diUzD5C3up8/edit?usp=sharing
- ECE260C Lab0- https://docs.google.com/document/d/1UtrIMVvUHBgF3RRtPc2sWJtAfYKMoURdmns-RxxP9aY/edit?tab=t.0#heading=h.1yjqu1dwtrtc


## Steps to validate the results

### Manual Script testing 
- To be able to validate the results you have to run this environment in your container assuming you have already installed OpenROAD and able to run ORFS there. 
- Clone this repository there and cd into the EDA-Corpus-v2 directory. Paste your result code into the flow_script.py or you can create a new python file and paste the script you want to test there.
- To run the script use following command
  
`openroad -python -exit name_of_your_script.py`

### Automated validation 
- To test the bench for generated scripts we have created a python script to automate the process.
- Put your .csv file in the EDA-Corpus-v2 directory. Update the name of the .csv file in the script accordingly.
- The script picks top 10 codes from the .csv file you can change this number as per your requirement. 
- Run the following code.
  `python3 script_name.py`
- After a successfull run you will be able to see the results in the results directory. You will find log file for each script ran along with that script. 

