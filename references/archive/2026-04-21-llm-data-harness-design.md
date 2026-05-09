LLM Data Analysis Harness: Master Design                                
                                                                                             
 Date: 2026-04-21                                                                            
 Status: Finalized (Pending User Review)                                                     
                                                                                             
 1. Overview                                                                                 
                                                                                             
 This document provides the high-level architectural roadmap for the LLM-driven data         
 analysis harness. It defines the "What" and the "Why" of the system, providing the context  
 for the detailed technical sub-specs.                                                       
                                                                                             
 2. Core Philosophy                                                                          
                                                                                             
 - The Brain-Body Split: Separating high-level reasoning (Brain) from low-level execution    
 (Body) to ensure reliability and isolation.                                                 
 - Atomic Tasking: Breaking complex queries into small, independent, and verifiable tasks.   
 - Auditability-First: Recording every decision, script, and result in a structured registry 
 to ensure provenance.                                                                       
 - The "Storage-Centric" State: Relying on a persistent, high-performance storage layer      
 (DuckDB/Files) to maintain state between isolated tasks.                                    
                                                                                             
 3. The Architecture: A Distributed Agentic Model                                            
                                                                                             
 The system consists of two primary, isolated components communicating via a structured      
 protocol.                                                                                   
                                                                                             
 ### 3.1 The Orchestrator (The "Brain")                                                      
                                                                                             
 The Brain is the central, stateful process responsible for the intelligence and user        
 interaction. It manages the "Plan-Execute-Replan" (PER) loop.                               
                                                                                             
 ### 3.2 The Worker (The "Body")                                                             
                                                                                             
 The Worker is a transient, isolated process responsible for the heavy-lifting of data       
 manipulation. It executes the code provided by the Brain.                                   
                                                                                             
 ### 3.3 The Bridge (The "Protocol")                                                         
                                                                                             
 The IPC (Inter-Process Communication) that connects the Brain and the Worker.               
                                                                                             
 ────────────────────────────────────────────────────────────────────────────────            
                                                                                             
 4. The Operational Workflow (The "Loop")                                                    
                                                                                             
 1. PLAN: The Brain analyzes the user query and generates a plan of atomic tasks.            
 2. CODE: The Brain generates the Python code for a specific task.                           
 3. EXECUTE: The Brain sends the code to the Worker.                                         
 4. OUTPUT: The Worker executes the code, saves the results (artifacts), and updates the     
 Manifest.                                                                                   
 5. INSPECT: The Brain reads the results from the Manifest and the generated .md files.      
 6. VERIFY: The Brain performs a self-verification check.                                    
 7. LOOP/FINISH: Based on the verification, the Brain either moves to the next task or       
 revises the plan.                                                                           
                                                                                             
 ────────────────────────────────────────────────────────────────────────────────            
                                                                                             
 5. Sub-Spec Roadmap                                                                         
                                                                                             
 To implement this system, we will follow these three detailed technical specifications:     
                                                                                             
 - Sub-Spec 1: The Brain-LLM Interface (The "Nervous System") - Focuses on the LLM           
 interaction and the PER loop.                                                               
 - Sub-Spec 2: The Worker-Protocol & Sandbox (The "Body") - Focuses on the IPC and process   
 isolation.                                                                                  
 - Sub-Spec 3: The Manifest & Data Schema (The "State") - Focuss on the structured data      
 registry and lineage. 