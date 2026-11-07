"""Явные ключи по полю и конечному URL без объединения по названию."""

import copy
import os
from threading import Thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from ..models import Run
from ..services.tasks_exec import publish_ready,run_one
from .fixtures.spec001_catalog import IdentityCatalog,identity_plan


class IdentityWithoutSkuTests(TestCase):
    def setUp(self):
        self.site=IdentityCatalog()
        Thread(target=self.site.serve_forever,daemon=True).start()
        self.addCleanup(self.site.server_close)
        self.addCleanup(self.site.shutdown)
        self.enterContext(patch.dict(os.environ,{'SCOUT_TASK_RUNNER':'inline',
            'SCOUT_TRUSTED_FETCH_ENDPOINTS':f'127.0.0.1:{self.site.server_port}'}))
        self.client=APIClient()
        self.user=get_user_model().objects.create_superuser(username='scout-identity-without-sku')
        self.client.force_authenticate(self.user)

    def plan(self,kind):
        plan=identity_plan(self.site.origin)
        if kind=='field':
            plan['fields'][0]['name']='external_id'
            plan['fields'][0]['selector']='.external-id'
            for path,body in self.site.pages.items():
                self.site.pages[path]=body.replace('class="sku"','class="external-id"')
            plan['identity']={'kind':'field','namespace':'external_catalog','field':'external_id'}
        else:
            plan['fields']=plan['fields'][1:]
            plan['identity']={'kind':'url','namespace':'url_catalog'}
        return plan

    def create(self,plan):
        response=self.client.post('/api/scout/jobs/',plan,format='json')
        self.assertEqual(response.status_code,201,response.data)
        return response.data['public_id']

    def collect(self,job):
        response=self.client.post(f'/api/scout/jobs/{job}/explore/')
        self.assertEqual(response.status_code,202,response.data)
        uid=response.data['public_id']
        publish_ready(uid)
        path=f'/api/scout/runs/{uid}/'
        preview=self.client.get(path,{'value_format':'typed_v1'}).data['preview']
        self.assertEqual(self.client.post(path+'approve/').status_code,200)
        self.client.post(path+'start/')
        publish_ready(uid)
        run=Run.objects.get(public_id=uid)
        self.assertEqual(run.status,'completed')
        return run,preview,self.client.get(path+'records/',{'value_format':'typed_v1'}).data['records']

    def test_field_key_groups_aliases_and_compares_changed_price(self):
        plan=self.plan('field')
        job=self.create(plan)
        base,preview,old=self.collect(job)
        self.assertEqual(len(old),3)
        self.assertEqual(len(preview),3)
        self.assertEqual(base.records.filter(entity_key__isnull=True).count(),1)
        first=next(row for row in old if row['identity']['key_value']=='K-01')
        self.assertEqual(first['identity']['kind'],'field')
        self.assertEqual(len(first['evidence']),6)
        for path in ('/products/k-01','/sale/k-01'):
            self.site.pages[path]=self.site.pages[path].replace('1 250,00','1 350,00')
        target,_preview,new=self.collect(job)
        response=self.client.get(f'/api/scout/runs/{target.public_id}/compare/',{
            'base_run_public_id':str(base.public_id),'field':'price'})
        self.assertEqual(response.status_code,200,response.data)
        changed=response.data['changes'][0]
        self.assertEqual(changed['key'],{'kind':'field','value':'K-01'})
        self.assertEqual(changed['status'],'changed')
        self.assertEqual(len(changed['before']['evidence']),2)
        self.assertEqual(len(changed['after']['evidence']),2)
        for task in target.tasks.all():
            self.assertFalse(run_one(str(task.public_id),task.fencing_token))
        self.assertEqual(target.records.count(),3)

    def test_url_key_keeps_same_names_at_different_urls_separate_and_is_stable(self):
        job=self.create(self.plan('url'))
        base,preview,old=self.collect(job)
        self.assertEqual(len(old),4)
        self.assertEqual(len(preview),4)
        self.assertEqual(base.records.filter(entity_key__isnull=True).count(),0)
        self.assertEqual({row['identity']['kind'] for row in old},{'url'})
        self.site.pages['/products/k-01']=self.site.pages['/products/k-01'].replace('1 250,00','1 350,00')
        target,_preview,new=self.collect(job)
        self.assertEqual({row['identity']['entity_key'] for row in old},{row['identity']['entity_key'] for row in new})
        response=self.client.get(f'/api/scout/runs/{target.public_id}/compare/',{
            'base_run_public_id':str(base.public_id),'field':'price'})
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['counts']['changed'],1)
        self.assertEqual(response.data['changes'][0]['key']['value'],self.site.origin+'/products/k-01')

    def test_url_normalization_uses_final_url_and_tracking_query_policy(self):
        from types import SimpleNamespace
        from ..services.product_identity import identity_extract_options
        revision=SimpleNamespace(identity={'kind':'url'},crawl={'drop_query':['utm_source']})
        snapshot=SimpleNamespace(source_url='https://example.com/alias',
                                 final_url='https://EXAMPLE.com:443/item?id=7&utm_source=demo#top')
        self.assertEqual(identity_extract_options(snapshot,revision),{'identity_url':'https://example.com/item?id=7'})

    def test_url_profile_rejects_repeated_cards_and_field_profiles_reject_bad_keys(self):
        plan=self.plan('url')
        plan['record']={'kind':'css','selector':'article'}
        result=self.client.post('/api/scout/jobs/',plan,format='json')
        self.assertEqual(result.status_code,400)
        self.assertEqual(result.data['code'],'invalid_identity')
        plan=self.plan('field')
        for change in ({'field':'absent'},{'kind':'automatic'}):
            invalid=copy.deepcopy(plan)
            invalid['identity'].update(change)
            self.assertEqual(self.client.post('/api/scout/jobs/',invalid,format='json').status_code,400)
        for field_change in ({'many':True},{'conversion':{'type':'integer'}}):
            invalid=copy.deepcopy(plan)
            invalid['fields'][0].update(field_change)
            self.assertEqual(self.client.post('/api/scout/jobs/',invalid,format='json').status_code,400)
