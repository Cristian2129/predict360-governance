# US-03 Part 2 — Privacy Review and Gap Report (Ley 1581 of 2012)

Project. FinBank Predict360, PCM Analytics
User Story. US-03, Part 2
Sprint: 2
Author: Paula Gacha

Status: Planning review, evidence requested

Scope:S ynthetic data and project documents, we did not have access to real information from FinBank customers


1. Purpose and scope:
The main idea of this review is to check what privacy things FinBank need to consider before using real customer data in Predict360
For now the project only use synthetic data about backlog, delinquency and churn, this mean that the information is not from real customers
Because of this, we cannot say if FinBank is following or not following the privacy laws in Colombia, we are only checking what is in our project and what things can be missing for the future
The main law for this review is Law 1581 of 2012, because it talks about personal data protection in Colombia
Also Law 1266 of 2008 is important because our project works with credit and delinquency information
Before using real data, the legal team of the bank need to check what rules apply for each type of information and how it will be used
This is just a first review for our academic project, it is not a final legal review


2. Legal criteria for Predict360:
There are some important things that we need to consider if the project will use real customer information in the future
Purpose of the information
Law 1581 of 2012, article 4
The bank need to be clear about why customer information is used, for example to identify delinquency problems or predict when a customer can leave the bank
Authorization and legal basis
Law 1581 of 2012, articles 4 and 9
We need to check if the bank have the correct permission or another valid legal reason to use the data, but not all financial information follow exactly the same rules, so this must be reviewed
Data quality
Law 1581 of 2012, article 4
Customer information need to be correct and complete, because wrong or missing values can affect the results and the decisions made with the data
Security and confidentiality
Law 1581 of 2012, articles 4 and 17
It is important to know who can see, change or share customer data, and make sure that not everyone can access this information
Customer rights
Law 1581 of 2012, articles 8 and 17
Customers have rights about their personal information, like asking to see it or correct something that is wrong, and in some cases request deletion
Financial and credit information
Law 1266 of 2008
Since Predict360 works with delinquency and financial information, we also need to check the special rules for this type of data before using real information


3. Preliminary gap review:
For this part we checked what we already have in the academic project and what things are still missing for a real version
Something important is that when we say information is missing, it does not mean the bank is doing something wrong, it only mean we did not have that evidence to review

-G01: Source and purpose
Priority: High
In our project we use synthetic CSV files for backlog, delinquency and churn
But we dont have documents showing where the real customer data will come from, who is responsible for it and what exact use is allowed
The action for this is to document the source of the information, the person responsible and the reason why the data is needed before using it

-G02: Legal basis and notices
Priority:High
For this academic project we did not receive real customer permissions or privacy notices
We still need to know what legal basis the bank can use and what information the customers should receive
The best action is to ask the privacy or legal team of FinBank to review this before we start using real data

-G03: Access and confidentiality
Priority: High
Right now we use a public GitHub repository because all our information is synthetic and is for the university project
But for a real bank we need more security, like private storage, access permissions and records of who use the information
The action is to never upload real customer data to a public GitHub repository and give access only to people who really need it

-G04: Data quality
Priority:Medium
In the first part of US 03 we found a problem in the churn dataset
There was 24 missing values in tenure months from a total of 200 records, this is 12 percent of the data
This is important because missing information can change how the prediction model works
For a real dataset we still need to know what is the correct way to fix those values
The action is to keep this finding in the quality report and later decide if the missing data should be corrected, completed with a valid method or removed, but only after checking the impact

-G05: Data retention and deletion
Priority: Medium
We did not have a document explaining how much time the real customer data should be saved
Also we dont have evidence of a process to delete the information in a safe way
The action is to define how long each dataset should be kept, who is responsible and how the data will be deleted when it is not needed anymore

-G06: Customer rights
Priority: Medium
For this academic review we did not receive a process about how real customers can make requests about their data
For example, when someone want to see their information or ask for a correction
The action is to create or document the procedure, the team responsible and the contact channel for customers

-G07: Financial data requirements
Priority: High
Our project include delinquency information because Predict360 is related with financial risk and customer analysis
But before working with real credit history, we need to know which extra rules apply under Law 1266 of 2008
The action is to make a legal review before any real credit information is added to the project


4. Priority action plan
After checking the previous points, these are the actions that we think are more important for the next steps

-Action 1: Check the purpose and access of the data
Priority:1
Responsible: FinBank business team and legal team
The first thing is to confirm why the real data will be used, who can access it and what laws apply
For evidence we should have approved documents about the use of data and access permissions

-Action 2:Check the source of real data
Priority:2
Responsible: Data owner and legal team
We need to know where the customer information comes from and if the bank have the correct legal basis to use it
The evidence can be a document with the sources, purposes and validated privacy notices or other legal basis

-Action 3: Improve security for real data<>
Priority:3
Responsible: IT and security team
The project need a safe place to store real information and access should be limited to authorized people
The evidence should include an access list, private storage and a plan to record the use of data

-Action 4: Review the missing values
Priority: 4
Responsible: Business Analyst and Data team
Before making predictions we need to decide what to do with the 12 percent missing values found in the synthetic churn dataset
The evidence will be the quality report from US 03 Part 1 and a document explaining the decision

-Action 5: Define how data is saved and deleted
Priority: 5
Responsible: Legal team and operations team
We need to define how long information can be stored and what process customers can use to ask about their information
The evidence should be a retention document and a procedure for customer requests

5. Conclusion

With this review we can see that our academic project is working with synthetic information and we already found one important problem related to data quality
The problem was the 24 missing values in the churn dataset, and this help us understand why checking data is important before making predictions
But this project does not prove that the real FinBank follow or dont follow all privacy laws, because we did not review real bank records or internal processes
Before using real customer information, the bank need to check the legal requirements, the purpose of the data, who can access it, the quality of the information and how long it will be stored
Also the bank need a process for customers who want to review or correct their personal data
In general, this review help us identify what things should be checked and what documents we still need for a real implementation
The missing evidence is not the same as saying the bank is breaking the law, it just show that we need more information before making that conclusion


6. Evidence for US 03 Part 2
For the pull request of this user story, the evidence should include this privacy review report
Also the quality report from US 03 Part 1, if it is available in the main branch of the repository
We also need a screenshot showing the complete report, the Trello card and the link of the pull request
This will help show what we did in this part of the sprint and what information we used for the review

7. References

 - 1. Departamento Administrativo de la Funcion Publica, Law 1581 of 2012, available in funcionpublica.gov.co

 - 2. Superintendencia de Industria y Comercio, Law 1581 of 2012, available in sedeelectronica.sic.gov.co

 - 3. Departamento Administrativo de la Funcion Publica, Law 1266 of 2008, available in funcionpublica.gov.co

 - 4. PCM Analytics, FinBank Predict360 repository, README and US 03 Part 1 quality report, project evidence from our team