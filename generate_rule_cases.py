import os
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import shutil

# Base output paths
PROJECT_ROOT = Path(__file__).parent.resolve()
TEST_SUITE_DIR = PROJECT_ROOT / "test_suite"
DMS_DIR = TEST_SUITE_DIR / "DMs"
CONFIG_DIR = TEST_SUITE_DIR / "config"
SCHEMAS_DIR = CONFIG_DIR / "schemas"

# Base descriptive DM template
BASE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE dmodule [
  <!NOTATION cgm SYSTEM "cgm">
  <!ENTITY ICN-F0210-AMAM0-001-01-F0210 SYSTEM "ICN-F0210-AMAM0-001-01-F0210.cgm" NDATA cgm>
  <!ENTITY invalid-icn-format SYSTEM "invalid-icn-format.cgm" NDATA cgm>
]>
<dmodule xmlns:dc="http://www.purl.org/dc/elements/1.1/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/descript.xsd">
   <identAndStatusSection>
      <dmAddress>
         <dmIdent>
            <dmCode modelIdentCode="JP" systemDiffCode="A000" systemCode="00" subSystemCode="0" subSubSystemCode="0" assyCode="0000" disassyCode="00" disassyCodeVariant="A" infoCode="001" infoCodeVariant="A" itemLocationCode="D" />
            <language countryIsoCode="EN" languageIsoCode="en" />
            <issueInfo issueNumber="001" inWork="00"/>
         </dmIdent>
         <dmAddressItems>
            <issueDate year="2026" month="03" day="10"/>
            <dmTitle>
               <techName>Test Technical Name</techName>
               <infoName>Test Information Name</infoName>
            </dmTitle>
         </dmAddressItems>
      </dmAddress>
      <dmStatus issueType="new">
         <security securityClassification="01" />
         <dataRestrictions>
            <restrictionInstructions>
               <dataDistribution/>
               <exportControl exportRegulationType="exp00">
                  <exportRegistrationStmt>
                     <simplePara>This data module contains technology submitted to Export Control. Transfer of this data to a foreign person without export approval is expressly prohibited.</simplePara>
                  </exportRegistrationStmt>
               </exportControl>
            </restrictionInstructions>
         </dataRestrictions>
         <responsiblePartnerCompany enterpriseCode="F0210"/>
         <originator enterpriseCode="F0210">
            <enterpriseName>F0210</enterpriseName>
         </originator>
         <applicRef applicIdentValue="ap01">
            <dmRef>
               <dmRefIdent>
                  <dmCode modelIdentCode="JP" systemDiffCode="A000" systemCode="00" subSystemCode="0" subSubSystemCode="0" assyCode="0000" disassyCode="00" disassyCodeVariant="A" infoCode="0A2" infoCodeVariant="A" itemLocationCode="D"/>
                  <language countryIsoCode="US" languageIsoCode="en"/>
               </dmRefIdent>
            </dmRef>
         </applicRef>
         <brexDmRef>
            <dmRef>
               <dmRefIdent>
                  <dmCode modelIdentCode="JP" systemDiffCode="A000" systemCode="00" subSystemCode="0" subSubSystemCode="0" assyCode="0000" disassyCode="00" disassyCodeVariant="A" infoCode="022" infoCodeVariant="A" itemLocationCode="D"/>
                  <language countryIsoCode="US" languageIsoCode="en"/>
               </dmRefIdent>
            </dmRef>
         </brexDmRef>
         <qualityAssurance>
            <firstVerification verificationType="tabtop" />
         </qualityAssurance>
         <reasonForUpdate updateReasonType="urt01" updateHighlight="0"><simplePara>Initial Release</simplePara></reasonForUpdate>
      </dmStatus>
   </identAndStatusSection>
   <content>
      <description>
         <levelledPara>
            <title>Valid Title</title>
            <para>This is a valid descriptive data module para element.</para>
             <figure>
                <title>Figure Title</title>
                <graphic infoEntityIdent="ICN-F0210-AMAM0-001-01-F0210"/>
             </figure>
             <table>
                <tgroup cols="1">
                   <tbody>
                      <row>
                         <entry>
                            <para>Flat Table Cell</para>
                         </entry>
                      </row>
                   </tbody>
                </tgroup>
             </table>
         </levelledPara>
      </description>
   </content>
</dmodule>
"""

# Base BREX template
BASE_BREX_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE dmodule [
  <!NOTATION cgm SYSTEM "cgm">
  <!ENTITY ICN-F0210-AMAM0-001-01-F0210 SYSTEM "ICN-F0210-AMAM0-001-01-F0210.cgm" NDATA cgm>
  <!ENTITY invalid-icn-format SYSTEM "invalid-icn-format.cgm" NDATA cgm>
]>
<dmodule xmlns:dc="http://www.purl.org/dc/elements/1.1/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/brex.xsd">
   <identAndStatusSection>
      <dmAddress>
         <dmIdent>
            <dmCode modelIdentCode="{MI}" systemDiffCode="A000" systemCode="00" subSystemCode="0" subSubSystemCode="0" assyCode="0000" disassyCode="00" disassyCodeVariant="A" infoCode="022" infoCodeVariant="A" itemLocationCode="D" />
            <language countryIsoCode="US" languageIsoCode="en" />
            <issueInfo issueNumber="001" inWork="00"/>
         </dmIdent>
         <dmAddressItems>
            <issueDate year="2026" month="03" day="10"/>
            <dmTitle>
               <techName>BREX</techName>
               <infoName>{MI} BREX rules</infoName>
            </dmTitle>
         </dmAddressItems>
      </dmAddress>
      <dmStatus issueType="new">
         <security securityClassification="01" />
         <dataRestrictions>
            <restrictionInstructions>
               <dataDistribution/>
               <exportControl exportRegulationType="exp00">
                  <exportRegistrationStmt>
                     <simplePara>This data module contains technology submitted to Export Control. Transfer of this data to a foreign person without export approval is expressly prohibited.</simplePara>
                  </exportRegistrationStmt>
               </exportControl>
            </restrictionInstructions>
         </dataRestrictions>
         <responsiblePartnerCompany enterpriseCode="F0210"/>
         <originator enterpriseCode="F0210">
            <enterpriseName>F0210</enterpriseName>
         </originator>
         <applicRef applicIdentValue="ap01">
            <dmRef>
               <dmRefIdent>
                  <dmCode modelIdentCode="{MI}" systemDiffCode="A000" systemCode="00" subSystemCode="0" subSubSystemCode="0" assyCode="0000" disassyCode="00" disassyCodeVariant="A" infoCode="0A2" infoCodeVariant="A" itemLocationCode="D"/>
                  <language countryIsoCode="US" languageIsoCode="en"/>
               </dmRefIdent>
            </dmRef>
         </applicRef>
         {PARENT_BREX_REF}
         <qualityAssurance>
            <firstVerification verificationType="tabtop" />
         </qualityAssurance>
         <reasonForUpdate updateReasonType="urt01" updateHighlight="0"><simplePara>Initial Release</simplePara></reasonForUpdate>
      </dmStatus>
   </identAndStatusSection>
   <content>
      <brex>
         <commonInfo>
            <para>{MI} rules module</para>
         </commonInfo>
         <contextRules rulesContext="http://www.s1000d.org/S1000D_4-1/xml_schema_flat/descript.xsd">
            <structureObjectRuleGroup>
               {RULES}
            </structureObjectRuleGroup>
         </contextRules>
      </brex>
   </content>
</dmodule>
"""

def make_parent_brex_ref(mi_code):
    if not mi_code:
        return "<brexDmRef/>"
    return f"""<brexDmRef>
            <dmRef>
               <dmRefIdent>
                  <dmCode modelIdentCode="{mi_code}" systemDiffCode="A000" systemCode="00" subSystemCode="0" subSubSystemCode="0" assyCode="0000" disassyCode="00" disassyCodeVariant="A" infoCode="022" infoCodeVariant="A" itemLocationCode="D"/>
                  <language countryIsoCode="US" languageIsoCode="en"/>
               </dmRefIdent>
            </dmRef>
         </brexDmRef>"""

def setup_directories():
    if DMS_DIR.exists():
        shutil.rmtree(DMS_DIR)
    if CONFIG_DIR.exists():
        shutil.rmtree(CONFIG_DIR)
    DMS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    
    src_schxslt = PROJECT_ROOT / "config" / "schxslt"
    dest_schxslt = CONFIG_DIR / "schxslt"
    if src_schxslt.exists():
        if dest_schxslt.exists():
            shutil.rmtree(dest_schxslt)
        shutil.copytree(src_schxslt, dest_schxslt)
        
    src_sch = PROJECT_ROOT / "config" / "S1000D_Business_Rules.sch"
    dest_sch = CONFIG_DIR / "S1000D_Business_Rules.sch"
    if src_sch.exists():
        shutil.copy2(src_sch, dest_sch)

    # Copy all XML BREX files from config folder to the test suite config folder
    for f in (PROJECT_ROOT / "config").glob("*.xml"):
        shutil.copy2(f, CONFIG_DIR / f.name)

def generate_cases():
    manifest = []
    
    # --- RULE CASE 1: JP Model Ident Code (BRDP-AH-34203JP) ---
    # Pos: modelIdentCode = JP
    # Neg: modelIdentCode = XX
    p1_dm = BASE_TEMPLATE
    p1_filename = "DMC-JP-A000-00-00-0000-00A-001A-D_001-00_en-US.xml"
    with open(DMS_DIR / p1_filename, "w", encoding="utf-8") as f:
        f.write(p1_dm)
    manifest.append({
        "filename": p1_filename,
        "expected_status": "valid",
        "rule_id": None
    })
    
    n1_dm = BASE_TEMPLATE.replace('modelIdentCode="JP"', 'modelIdentCode="XX"')
    n1_filename = "DMC-XX-A000-00-00-0000-00A-001A-D_001-00_en-US.xml"
    with open(DMS_DIR / n1_filename, "w", encoding="utf-8") as f:
        f.write(n1_dm)
    manifest.append({
        "filename": n1_filename,
        "expected_status": "invalid",
        "rule_id": "BRDP-AH-34203JP"
    })
    
    # --- RULE CASE 2: languageIsoCode (BRDP-AH-42038JP) ---
    # Pos: languageIsoCode = en
    # Neg: languageIsoCode = it
    p2_dm = BASE_TEMPLATE.replace('infoCode="001"', 'infoCode="002"')
    p2_filename = "DMC-JP-A000-00-00-0000-00A-002A-D_001-00_en-US.xml"
    with open(DMS_DIR / p2_filename, "w", encoding="utf-8") as f:
        f.write(p2_dm)
    manifest.append({
        "filename": p2_filename,
        "expected_status": "valid",
        "rule_id": None
    })
    
    n2_dm = BASE_TEMPLATE.replace('languageIsoCode="en"', 'languageIsoCode="it"')
    n2_dm = n2_dm.replace('countryIsoCode="EN"', 'countryIsoCode="IT"')
    n2_dm = n2_dm.replace('infoCode="001" infoCodeVariant="A"', 'infoCode="002" infoCodeVariant="B"')
    n2_filename = "DMC-JP-A000-00-00-0000-00A-002B-D_001-00_en-US.xml"
    with open(DMS_DIR / n2_filename, "w", encoding="utf-8") as f:
        f.write(n2_dm)
    manifest.append({
        "filename": n2_filename,
        "expected_status": "invalid",
        "rule_id": "BRDP-AH-42038JP"
    })

    # --- RULE CASE 3: countryIsoCode (BRDP-AH-42039JP) ---
    # Pos: countryIsoCode = EN (when languageIsoCode is en)
    # Neg: countryIsoCode = US (when languageIsoCode is en)
    p3_dm = BASE_TEMPLATE.replace('infoCode="001"', 'infoCode="003"')
    p3_filename = "DMC-JP-A000-00-00-0000-00A-003A-D_001-00_en-US.xml"
    with open(DMS_DIR / p3_filename, "w", encoding="utf-8") as f:
        f.write(p3_dm)
    manifest.append({
        "filename": p3_filename,
        "expected_status": "valid",
        "rule_id": None
    })
    
    n3_dm = BASE_TEMPLATE.replace('countryIsoCode="EN"', 'countryIsoCode="US"')
    n3_dm = n3_dm.replace('infoCode="001" infoCodeVariant="A"', 'infoCode="003" infoCodeVariant="B"')
    n3_filename = "DMC-JP-A000-00-00-0000-00A-003B-D_001-00_en-US.xml"
    with open(DMS_DIR / n3_filename, "w", encoding="utf-8") as f:
        f.write(n3_dm)
    manifest.append({
        "filename": n3_filename,
        "expected_status": "invalid",
        "rule_id": "BRDP-AH-42039JP"
    })

    # --- RULE CASE 4: caveat (BRDP-AH-85001JP) ---
    # Pos: caveat = cv51
    # Neg: caveat = cv99
    p4_dm = BASE_TEMPLATE.replace('<security securityClassification="01" />', '<security securityClassification="01" caveat="cv51"/>')
    p4_dm = p4_dm.replace('infoCode="001"', 'infoCode="004"')
    p4_filename = "DMC-JP-A000-00-00-0000-00A-004A-D_001-00_en-US.xml"
    with open(DMS_DIR / p4_filename, "w", encoding="utf-8") as f:
        f.write(p4_dm)
    manifest.append({
        "filename": p4_filename,
        "expected_status": "valid",
        "rule_id": None
    })
    
    n4_dm = BASE_TEMPLATE.replace('<security securityClassification="01" />', '<security securityClassification="01" caveat="cv99"/>')
    n4_dm = n4_dm.replace('infoCode="001" infoCodeVariant="A"', 'infoCode="004" infoCodeVariant="B"')
    n4_filename = "DMC-JP-A000-00-00-0000-00A-004B-D_001-00_en-US.xml"
    with open(DMS_DIR / n4_filename, "w", encoding="utf-8") as f:
        f.write(n4_dm)
    manifest.append({
        "filename": n4_filename,
        "expected_status": "invalid",
        "rule_id": "BRDP-AH-85001JP"
    })

    # --- RULE CASE 5: security classification (BRDP-AH-99043JP) ---
    # Pos: securityClassification = 01
    # Neg: securityClassification = 03
    p5_dm = BASE_TEMPLATE.replace('infoCode="001"', 'infoCode="005"')
    p5_filename = "DMC-JP-A000-00-00-0000-00A-005A-D_001-00_en-US.xml"
    with open(DMS_DIR / p5_filename, "w", encoding="utf-8") as f:
        f.write(p5_dm)
    manifest.append({
        "filename": p5_filename,
        "expected_status": "valid",
        "rule_id": None
    })
    
    n5_dm = BASE_TEMPLATE.replace('securityClassification="01"', 'securityClassification="03"')
    n5_dm = n5_dm.replace('infoCode="001" infoCodeVariant="A"', 'infoCode="005" infoCodeVariant="B"')
    n5_filename = "DMC-JP-A000-00-00-0000-00A-005B-D_001-00_en-US.xml"
    with open(DMS_DIR / n5_filename, "w", encoding="utf-8") as f:
        f.write(n5_dm)
    manifest.append({
        "filename": n5_filename,
        "expected_status": "invalid",
        "rule_id": "BRDP-AH-99043JP"
    })

    # --- RULE CASE 6: Schematron dm-integrity ---
    # Pos: filename matches dmc attributes
    # Neg: filename does not match
    p6_dm = BASE_TEMPLATE.replace('infoCode="001"', 'infoCode="006"')
    p6_filename = "DMC-JP-A000-00-00-0000-00A-006A-D_001-00_en-US.xml"
    with open(DMS_DIR / p6_filename, "w", encoding="utf-8") as f:
        f.write(p6_dm)
    manifest.append({
        "filename": p6_filename,
        "expected_status": "valid",
        "rule_id": None
    })
    
    # We change assyCode in XML content to 9999, but we keep the filename using 0000.
    # This triggers dm-integrity error.
    n6_dm = BASE_TEMPLATE.replace('assyCode="0000"', 'assyCode="9999"', 1)
    n6_dm = n6_dm.replace('infoCode="001" infoCodeVariant="A"', 'infoCode="006" infoCodeVariant="B"')
    n6_filename = "DMC-JP-A000-00-00-0000-00A-006B-D_001-00_en-US.xml"
    with open(DMS_DIR / n6_filename, "w", encoding="utf-8") as f:
        f.write(n6_dm)
    manifest.append({
        "filename": n6_filename,
        "expected_status": "invalid",
        "rule_id": "dm-integrity"
    })

    # --- RULE CASE 7: Schematron content-quality/title ---
    # Pos: title is "Valid Title"
    # Neg: title is empty
    p7_dm = BASE_TEMPLATE.replace('infoCode="001"', 'infoCode="007"')
    p7_filename = "DMC-JP-A000-00-00-0000-00A-007A-D_001-00_en-US.xml"
    with open(DMS_DIR / p7_filename, "w", encoding="utf-8") as f:
        f.write(p7_dm)
    manifest.append({
        "filename": p7_filename,
        "expected_status": "valid",
        "rule_id": None
    })
    
    n7_dm = BASE_TEMPLATE.replace('<title>Valid Title</title>', '<title></title>')
    n7_dm = n7_dm.replace('infoCode="001" infoCodeVariant="A"', 'infoCode="007" infoCodeVariant="B"')
    n7_filename = "DMC-JP-A000-00-00-0000-00A-007B-D_001-00_en-US.xml"
    with open(DMS_DIR / n7_filename, "w", encoding="utf-8") as f:
        f.write(n7_dm)
    manifest.append({
        "filename": n7_filename,
        "expected_status": "invalid",
        "rule_id": "content-quality"
    })

    # --- RULE CASE 8: Schematron content-quality/graphic ---
    # Pos: infoEntityIdent="ICN-12345-A-B-C"
    # Neg: infoEntityIdent="invalid-icn-format"
    p8_dm = BASE_TEMPLATE.replace('infoCode="001"', 'infoCode="008"')
    p8_filename = "DMC-JP-A000-00-00-0000-00A-008A-D_001-00_en-US.xml"
    with open(DMS_DIR / p8_filename, "w", encoding="utf-8") as f:
        f.write(p8_dm)
    manifest.append({
        "filename": p8_filename,
        "expected_status": "valid",
        "rule_id": None
    })
    
    n8_dm = BASE_TEMPLATE.replace('infoEntityIdent="ICN-F0210-AMAM0-001-01-F0210"', 'infoEntityIdent="invalid-icn-format"')
    n8_dm = n8_dm.replace('infoCode="001" infoCodeVariant="A"', 'infoCode="008" infoCodeVariant="B"')
    n8_filename = "DMC-JP-A000-00-00-0000-00A-008B-D_001-00_en-US.xml"
    with open(DMS_DIR / n8_filename, "w", encoding="utf-8") as f:
        f.write(n8_dm)
    manifest.append({
        "filename": n8_filename,
        "expected_status": "invalid",
        "rule_id": "content-quality"
    })

    # --- RULE CASE 9: Schematron content-quality/security ---
    # Pos: class="01"
    # Neg: class="06"
    p9_dm = BASE_TEMPLATE.replace('infoCode="001"', 'infoCode="009"')
    p9_filename = "DMC-JP-A000-00-00-0000-00A-009A-D_001-00_en-US.xml"
    with open(DMS_DIR / p9_filename, "w", encoding="utf-8") as f:
        f.write(p9_dm)
    manifest.append({
        "filename": p9_filename,
        "expected_status": "valid",
        "rule_id": None
    })
    
    n9_dm = BASE_TEMPLATE.replace('<security securityClassification="01" />', '<security securityClassification="06" />')
    n9_dm = n9_dm.replace('infoCode="001" infoCodeVariant="A"', 'infoCode="009" infoCodeVariant="B"')
    n9_filename = "DMC-JP-A000-00-00-0000-00A-009B-D_001-00_en-US.xml"
    with open(DMS_DIR / n9_filename, "w", encoding="utf-8") as f:
        f.write(n9_dm)
    manifest.append({
        "filename": n9_filename,
        "expected_status": "invalid",
        "rule_id": "content-quality"
    })

    # --- RULE CASE 10: Schematron complexity/table ---
    # Pos: flat table
    # Neg: nested table
    p10_dm = BASE_TEMPLATE.replace('infoCode="001"', 'infoCode="010"')
    p10_filename = "DMC-JP-A000-00-00-0000-00A-010A-D_001-00_en-US.xml"
    with open(DMS_DIR / p10_filename, "w", encoding="utf-8") as f:
        f.write(p10_dm)
    manifest.append({
        "filename": p10_filename,
        "expected_status": "valid",
        "rule_id": None
    })
    
    n10_nested_table = """<table>
               <tgroup cols="1">
                  <tbody>
                     <row>
                        <entry>
                           <table>
                              <tgroup cols="1">
                                 <tbody>
                                    <row>
                                       <entry>
                                          <para>Nested Table Cell</para>
                                       </entry>
                                    </row>
                                 </tbody>
                              </tgroup>
                           </table>
                        </entry>
                     </row>
                  </tbody>
               </tgroup>
            </table>"""
    n10_dm = BASE_TEMPLATE.replace('<para>Flat Table Cell</para>', f'<para>Flat Table Cell</para>{n10_nested_table}')
    n10_dm = n10_dm.replace('infoCode="001" infoCodeVariant="A"', 'infoCode="010" infoCodeVariant="B"')
    n10_filename = "DMC-JP-A000-00-00-0000-00A-010B-D_001-00_en-US.xml"
    with open(DMS_DIR / n10_filename, "w", encoding="utf-8") as f:
        f.write(n10_dm)
    manifest.append({
        "filename": n10_filename,
        "expected_status": "invalid",
        "rule_id": "complexity"
    })

    return manifest

def generate_chain_cases(manifest):
    # Generate cascading BREX reference files in test_suite/config/
    # Base grandparent BREX: CHAINBASE
    rules_base = """<structureObjectRule id="RULE-BASE-01">
                  <objectPath allowedObjectFlag="0">/dmodule[./identAndStatusSection/dmStatus/originator/enterpriseName[not(text()='BASE')]]</objectPath>
                  <objectUse>[RULE-BASE-01] Originator name must be BASE.</objectUse>
               </structureObjectRule>"""
    brex_base = BASE_BREX_TEMPLATE.format(MI="CHAINBASE", PARENT_BREX_REF="<brexDmRef/>", RULES=rules_base)
    with open(CONFIG_DIR / "DMC-CHAINBASE-A000-00-00-0000-00A-022A-D_001-00_en-US.xml", "w", encoding="utf-8") as f:
        f.write(brex_base)

    # Parent BREX: CHAINMID, references CHAINBASE
    rules_mid = """<structureObjectRule id="RULE-MID-01">
                  <objectPath allowedObjectFlag="0">/dmodule[./identAndStatusSection/dmStatus/responsiblePartnerCompany[@enterpriseCode != 'MID']]</objectPath>
                  <objectUse>[RULE-MID-01] Responsible Partner Company must be MID.</objectUse>
               </structureObjectRule>"""
    brex_mid = BASE_BREX_TEMPLATE.format(MI="CHAINMID", PARENT_BREX_REF=make_parent_brex_ref("CHAINBASE"), RULES=rules_mid)
    with open(CONFIG_DIR / "DMC-CHAINMID-A000-00-00-0000-00A-022A-D_001-00_en-US.xml", "w", encoding="utf-8") as f:
        f.write(brex_mid)

    # Project BREX: CHAINTOP, references CHAINMID
    rules_top = """<structureObjectRule id="RULE-TOP-01">
                  <objectPath allowedObjectFlag="0">/dmodule[./identAndStatusSection/dmAddress/dmAddressItems/dmTitle/techName[not(text()='TOP')]]</objectPath>
                  <objectUse>[RULE-TOP-01] Tech name must be TOP.</objectUse>
               </structureObjectRule>"""
    brex_top = BASE_BREX_TEMPLATE.format(MI="CHAINTOP", PARENT_BREX_REF=make_parent_brex_ref("CHAINMID"), RULES=rules_top)
    with open(CONFIG_DIR / "DMC-CHAINTOP-A000-00-00-0000-00A-022A-D_001-00_en-US.xml", "w", encoding="utf-8") as f:
        f.write(brex_top)

    print("Generated 3 chain BREX files in test_suite/config/")

    # Generate the 4 DMs to test the chain
    def make_chain_dm(info_code, info_code_variant, tech_name, rpc_name, originator_name):
        dm = BASE_TEMPLATE
        dm = dm.replace('modelIdentCode="JP" systemDiffCode="A000" systemCode="00" subSystemCode="0" subSubSystemCode="0" assyCode="0000" disassyCode="00" disassyCodeVariant="A" infoCode="022" infoCodeVariant="A" itemLocationCode="D"/>',
                        'modelIdentCode="CHAINTOP" systemDiffCode="A000" systemCode="00" subSystemCode="0" subSubSystemCode="0" assyCode="0000" disassyCode="00" disassyCodeVariant="A" infoCode="022" infoCodeVariant="A" itemLocationCode="D"/>')
        dm = dm.replace('modelIdentCode="JP" systemDiffCode="A000" systemCode="00" subSystemCode="0" subSubSystemCode="0" assyCode="0000" disassyCode="00" disassyCodeVariant="A" infoCode="0A2" infoCodeVariant="A" itemLocationCode="D"/>',
                        'modelIdentCode="CHAINTOP" systemDiffCode="A000" systemCode="00" subSystemCode="0" subSubSystemCode="0" assyCode="0000" disassyCode="00" disassyCodeVariant="A" infoCode="0A2" infoCodeVariant="A" itemLocationCode="D"/>')
        dm = dm.replace('infoCode="001" infoCodeVariant="A"', f'infoCode="{info_code}" infoCodeVariant="{info_code_variant}"')
        dm = dm.replace('<techName>Test Technical Name</techName>', f'<techName>{tech_name}</techName>')
        dm = dm.replace('<responsiblePartnerCompany enterpriseCode="F0210"/>', f'<responsiblePartnerCompany enterpriseCode="{rpc_name}"/>')
        dm = dm.replace('<originator enterpriseCode="F0210">', f'<originator enterpriseCode="{originator_name}">')
        dm = dm.replace('<enterpriseName>F0210</enterpriseName>', f'<enterpriseName>{originator_name}</enterpriseName>')
        return dm

    # Pos case: all correct
    p_filename = "DMC-JP-A000-00-00-0000-00A-011A-D_001-00_en-US.xml"
    with open(DMS_DIR / p_filename, "w", encoding="utf-8") as f:
        f.write(make_chain_dm("011", "A", "TOP", "MID", "BASE"))
    manifest.append({
        "filename": p_filename,
        "expected_status": "valid",
        "rule_id": None
    })

    # Neg case 1: Top fails
    n_top_filename = "DMC-JP-A000-00-00-0000-00A-011B-D_001-00_en-US.xml"
    with open(DMS_DIR / n_top_filename, "w", encoding="utf-8") as f:
        f.write(make_chain_dm("011", "B", "BADTOP", "MID", "BASE"))
    manifest.append({
        "filename": n_top_filename,
        "expected_status": "invalid",
        "rule_id": "RULE-TOP-01"
    })

    # Neg case 2: Mid fails
    n_mid_filename = "DMC-JP-A000-00-00-0000-00A-011C-D_001-00_en-US.xml"
    with open(DMS_DIR / n_mid_filename, "w", encoding="utf-8") as f:
        f.write(make_chain_dm("011", "C", "TOP", "BADMID", "BASE"))
    manifest.append({
        "filename": n_mid_filename,
        "expected_status": "invalid",
        "rule_id": "RULE-MID-01"
    })

    # Neg case 3: Base fails
    n_base_filename = "DMC-JP-A000-00-00-0000-00A-011D-D_001-00_en-US.xml"
    with open(DMS_DIR / n_base_filename, "w", encoding="utf-8") as f:
        f.write(make_chain_dm("011", "D", "TOP", "MID", "BADBASE"))
    manifest.append({
        "filename": n_base_filename,
        "expected_status": "invalid",
        "rule_id": "RULE-BASE-01"
    })

    print("Generated 4 chain-test DMs in test_suite/DMs/")

if __name__ == "__main__":
    setup_directories()
    manifest = generate_cases()
    generate_chain_cases(manifest)
    
    with open(TEST_SUITE_DIR / "test_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=4)
        
    print(f"Generated total of {len(manifest)} rule test XML files in test_suite/DMs/")
