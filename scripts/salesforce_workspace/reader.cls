public with sharing class __CLASS__ {
    private static Map<String, String> scope() {
        return new Map<String, String>{__SCOPE__};
    }
    @AuraEnabled
    public static List<SObject> readRecords(String objectName, Id recordId) {
        Map<String, String> allowed = scope();
        if (!allowed.containsKey(objectName)) {
            throw new AuraHandledException('Object is outside the reviewed application scope');
        }
        String fields = recordId == null ? 'Id, Name' : 'Id, Name, LastModifiedDate, ' + allowed.get(objectName);
        String query = 'SELECT ' + fields + ' FROM ' + objectName;
        Map<String, Object> binds = new Map<String, Object>();
        if (recordId != null) {
            if (recordId.getSObjectType().getDescribe().getName() != objectName) {
                throw new AuraHandledException('Record belongs to a different object');
            }
            query += ' WHERE Id = :selectedId';
            binds.put('selectedId', recordId);
        }
        query += ' ORDER BY LastModifiedDate DESC LIMIT 50';
        return Database.queryWithBinds(query, binds, AccessLevel.USER_MODE);
    }
}
