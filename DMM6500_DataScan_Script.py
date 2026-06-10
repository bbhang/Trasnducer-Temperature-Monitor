import numpy as np
import pandas as pd
from pathlib import Path
from tkinter import filedialog


# get the file to convert
data_file = filedialog.askopenfilename(title="Choose the Sensor Readings File")

# Read CSV File into a dataframe
dataTable=pd.read_csv(data_file,skiprows=8)

#Rearrange data
##Remove extra columns
print("Raw Data Table")
print(dataTable)
dataTable=dataTable.drop(['Range Digits','Disp Digits','Math','Start Group','Limit1 High','Limit1 Low','Limit2 High','Limit2 Low','Terminal','Questionable','Origin','CH Label'],axis=1)
print("Cleanup Columns")
print(dataTable)


## Get Number of Channels
numChannels=dataTable['Channel'].nunique()
numData=dataTable.shape[0]
## Rearrange datastructure
dTWide=dataTable.pivot_table(index=["Relative Time"],columns='Channel',values='Reading')
print("Rearranged")
print(dTWide)
## Save as CSV
dTWide.to_csv(data_file[0:len(data_file)-5]+"_Rearranged.csv")