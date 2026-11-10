<?xml version="1.0" encoding="UTF-8"?>
<schema xmlns="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">
    <title>S1000D Business Rules (v8.7.0)</title>
    
    <ns prefix="s" uri="http://purl.oclc.org/dsdl/svrl"/>
    
    <pattern id="dm-integrity">
        <rule context="dmCode">
            <let name="dmc" select="string-join((@modelIdentCode, @systemDiffCode, @systemCode, concat(@subSystemCode, @subSubSystemCode), @assyCode, concat(@disassyCode, @disassyCodeVariant), concat(@infoCode, @infoCodeVariant), @itemLocationCode), '-')"/>
            <!-- Get filename from base-uri (handles both slash types) -->
            <let name="filename" select="replace(tokenize(base-uri(), '[/\\%]')[last()], '\.[xX][mM][lL]$', '')"/>
            
            <assert test="starts-with(upper-case($filename), upper-case($dmc))">
                CRITICAL: The DMC defined inside the XML (<value-of select="$dmc"/>) does not match the filename (<value-of select="$filename"/>). This breaks S1000D naming conventions.
            </assert>
        </rule>
    </pattern>

    <pattern id="content-quality">
        <rule context="title">
            <assert test="normalize-space(.)">
                QUALITY: Found an empty title. All elements must have descriptive titles for the Analyst Viewer.
            </assert>
        </rule>
        
        <rule context="graphic">
            <assert test="matches(@infoEntityIdent, '^ICN-[A-Z0-9\-]+$')">
                FORMAT: Invalid ICN format '<value-of select="@infoEntityIdent"/>'. S1000D graphics must follow the 'ICN-MODEL-...' pattern.
            </assert>
        </rule>

        <rule context="security">
            <assert test="@securityClassification = ('01', '02', '03', '04', '05')">
                SECURITY: Invalid classification level '<value-of select="@securityClassification"/>'. Must be 01 (Unclassified) to 05 (Top Secret).
            </assert>
        </rule>
    </pattern>

    <pattern id="complexity">
        <rule context="table">
            <report test="descendant::table">
                DESIGN: Nested tables detected. S1000D recommends flat table structures for better mobile/web rendering.
            </report>
        </rule>
    </pattern>
</schema>
