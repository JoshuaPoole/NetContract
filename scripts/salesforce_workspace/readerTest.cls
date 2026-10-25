@IsTest
private class __CLASS__Test {
    @IsTest static void rejectsUnreviewedObject() {
        Boolean rejected = false;
        try {
            __CLASS__.readRecords('Account', null);
        } catch (AuraHandledException expected) {
            rejected = true;
        }
        System.assert(rejected, 'Unreviewed objects must not be queried');
    }
    @IsTest static void readsReviewedScopeWithoutData() {
        List<SObject> rows = __CLASS__.readRecords('__FIRST_OBJECT__', null);
        System.assertEquals(0, rows.size(), 'No synthetic incident fallback');
    }
}
