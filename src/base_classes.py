'''
SplunkML base classes

Ankit Kumar
ankitk@stanford.edu


'''

import splunklib.client as client
import splunklib.results as results
#from sklearn.naive_bayes import BernoulliNB
#from sklearn.linear_model import LogisticRegression
from collections import defaultdict
import numpy as np
import sys


class SplunkBase(object):
	'''
	base of splunk objects; mainly has an __init__ function
	'''
	def __init__(self, host, port, username, password):
		self.service = client.connect(host=host, port=port, username=username, password=password)
		self.jobs = self.service.jobs
		self.trained = False
		self.feature_fields = None
		self.accuracy_tested = False
		self.feature_mapping = {}
		self.class_mapping = {}

class SplunkProjectorBase(SplunkBase):
	''' SplunkProjectorBase

	Base class of splunk ML objects that do dimensionality reduction (projections)

	'''
	def __init__(self, host, port, username, password):
		super(SplunkProjectorBase, self).__init__(host, port, username, password)

### -- [FUNCTIONS TO OVERWRITE] -- ###	

	def project_splunk_search():
		'''
			to overwrite

			must return a splunk search string that ends with an eval output_field_i_j = i,j'th value of the projection
		'''
		raise NotImplementedError

	def project_single_event():
		'''
			to overwrite

			must return a projection of X_fields
		'''
		raise NotImplementedError


	def train():
		'''
			to overwrite

			must train params on the data returned by search_string, and store params in the class
		'''
		raise NotImplementedError	



class SplunkPredictorBase(SplunkBase):
	''' SplunkPredictorBase

	Base class of splunk predictors.

	'''


	def __init__(self, host, port, username, password):
		super(SplunkPredictorBase, self).__init__(host, port, username, password)


### -- [FUNCTIONS TO OVERWRITE] -- ##


	def predict_splunk_search(self, search_string, X_fields, Y_field, output_field):
		'''
			to overwrite

			must return a splunk search string that ends with an eval output_field = prediction term
		'''
		raise NotImplementedError

	def predict_single_event(self, event_to_predict, X_fields, Y_field):
		'''
			to overwrite

			must return a prediction for Y_field of event_to_predict. prediction is a string.
		'''
		raise NotImplementedError


	def train(self, search_string, X_fields, Y_field):
		'''
			to overwrite

			must train params on the data returned by search_string, and store params in the class
		'''
		raise NotImplementedError		




### -- Splunk Classifier Base -- ##

class SplunkClassifierBase(SplunkPredictorBase):
	'''
	base class for splunk classifiers (i.e discrete not continuous)
	'''

	def test_accuracy_splunk_search(self, train_search, test_search, X_fields, Y_field):
		'''
			tests the classifier's accuracy using its predict_splunk_search method. trains on the data found in
			train_search, tests on the data found in test_search.
		'''
		#1: train the classifier
		self.train(train_search, X_fields, Y_field)

		#2: predict the test search
		prediction_search = self.predict_splunk_search(test_search, X_fields, Y_field, 'test_predict_UNIQ')

		#3: calculate accuracy from test set
		accuracy, correct = self.calculate_accuracy_from_splunk_prediction_search(prediction_search, Y_field)

		#4: report accuracy
		print "#### test_accuracy_splunk_search: %f, num correct: %d" % (accuracy, correct)
		return accuracy
		

	def test_accuracy_single_event(self, train_search, test_search, X_fields, Y_field):
		'''
			tests the classifier's accuracy using its predict_single_event method. trains on the data
			found in train_search, tests on the data found in test_search.
		'''
		#1: train the classifier
		self.train(train_search, X_fields, Y_field)

		#2: run the test search, and iterate through events to get accuracy
		accuracy, correct = self.calculate_accuracy_from_single_events(test_search, X_fields, Y_field)

		print "#### test_accuracy_single_event: %f, num correct: %d" % (accuracy, correct)
		return accuracy



## -- [HELPER FUNCTIONS FOR THE BASE CLASS] -- ##

	def calculate_accuracy_from_single_events(self, test_search, X_fields, Y_field):
		#1: run the splunk search
		search_kwargs = {'timeout':1000, 'exec_mode':'blocking'}
		job = self.jobs.create('search %s | table %s %s' % (test_search, ' '.join(X_fields), Y_field), **search_kwargs)

		#2: iterate through the results
		
		correct = 0
		total = float(job["resultCount"])
		offset = 0
		count = 100
		print "iterating"
		# iterate
		while (offset < total):
			kwargs_paginate = {'count': count, 'offset':offset}
			search_results = job.results(**kwargs_paginate)
			for result in results.ResultsReader(search_results):
				# result is an EVENT
				if Y_field not in result:
					continue # this probably should be checked; if we accidentally foudn a non-event.
				else:
					prediction  = self.predict_single_event(result, X_fields, Y_field)
					
					if prediction == result[Y_field]:
						correct += 1
			offset += count
		
		return correct/total, correct


	def calculate_accuracy_from_splunk_prediction_search(self, prediction_search, Y_field):
		#1: cut the fields to just the ones we're interested in
		prediction_search += '| table %s, test_predict_UNIQ' % Y_field

		#2: run the job
		search_kwargs = {'timeout':1000, 'exec_mode':'blocking'}
		job = self.jobs.create(prediction_search, **search_kwargs)

		#3: iterate through the job and count accuracy
		# set up variables
		correct = 0
		total = float(job["resultCount"]) #float for the later accuracy calculation
		offset = 0
		count = 100
		print "iterating"
		#iterate
		while (offset < total):
			kwargs_paginate = {'count': count, 'offset':offset}
			search_results = job.results(**kwargs_paginate)
			for result in results.ResultsReader(search_results):
				if Y_field not in result or 'test_predict_UNIQ' not in result:
					continue #this probably should be checked 
				if result[Y_field] == result['test_predict_UNIQ']:
					correct += 1
			offset += count
			print offset

		#return accuracy
		return correct/total, correct






	def check_accuracy(self, search_string, feature_fields, class_field):
		'''
			check_accuracy(search_string, feature_fields, class_field)

			search_string: string to use in the splunk search to narrow events
			feature_fields: which fields to use to predict
			class_field: field to predict

			returns: accuracy of prediction

			notes: assumes that classifier is already trained. calls predict on each event.
		'''
		# 1: check that classifier is trained:
		if not self.trained:
			raise 'classifier is not trained'


		# 2: predict the search string
		splunk_search = 'search %s | table *' % search_string
		search_kwargs = {'timeout':1000, 'exec_mode':'blocking'} #required fields set to all - check API ("rf=*")
		job = self.jobs.create(splunk_search, **search_kwargs)
		result_count = int(job["resultCount"])

		# 3: iterate and tally accuracy
		correct = 0
		total = 0
		offset = 0
		count = 100
		while (offset < result_count):
			print "offset: %s" % offset
			kwargs_paginate = {'count': count, 'offset':offset}
			search_results = job.results(**kwargs_paginate)
			for result in results.ResultsReader(search_results):
				try:
					if result[class_field] == self.predict(feature_fields, class_field, result):
						correct += 1
						total += 1
					else:
						total += 1
				except:
					continue #tochange
		
			offset += count
			print "curr acc: %f" % (float(correct) / total)

		# 4: calculate percentage
		perc_correct = float(correct)/total
		self.accuracy = perc_correct
		self.accuracy_tested = True

		# 5: return
		return perc_correct



	def evaluate_accuracy(self, search_string, feature_fields, class_field):
		'''
			evaluate_accuracy()

			trains the classifier, then predicts each of the events it trains on and records how many were correct
		'''
		print "Now evaluating %s test set accuracy." % self.__class__.__name__

		#1 : train the classifier
		print "--> Training the classifier..."
		self.train(search_string, feature_fields, class_field)
		print "... done."

		#2 : check accuracy
		print "--> Iterating through test set and checking accuracy..."
		accuracy = self.check_accuracy(search_string, feature_fields, class_field)
		print "done."

		#3 : print result
		print "Accuracy was %f." % accuracy


class SplunkRegressorBase(SplunkPredictorBase):
	'''
	base class for splunk regressors (i.e continuous not discrete). terminology of 'regressor' might be wrong..
	'''

	def test_accuracy_splunk_search(self, train_search, test_search, X_fields, Y_field):
		'''
			tests the classifier's accuracy using its predict_splunk_search method. trains on the data found in
			train_search, tests on the data found in test_search. Uses the evaluation metric of ...
		'''
		#1: train the classifier
		self.train(train_search, X_fields, Y_field)

		#2: predict the test search
		prediction_search = self.predict_splunk_search(test_search, X_fields, Y_field, '_test_predict')

		#3: calculate accuracy from test set
		accuracy = self.calculate_accuracy_from_splunk_prediction_search(prediction_search, Y_field)

		#4: report accuracy
		print "#### test_accuracy_splunk_search: %f" % accuracy
		return accuracy
		

	def test_accuracy_single_event(self, train_search, test_search, X_fields, Y_field):
		'''
			tests the classifier's accuracy using its predict_single_event method. trains on the data
			found in train_search, tests on the data found in test_search.
		'''
		
		#1: train the classifier
		self.train(train_search, X_fields, Y_field)

		#2: run the test search, and iterate through events to get accuracy
		accuracy = self.calculate_accuracy_from_single_events(test_search, X_fields, Y_field)

		print "#### test_cost_function_single_event: %f" % accuracy
		return accuracy



## -- [HELPER FUNCTIONS FOR THE BASE CLASS] -- ##

	def calculate_accuracy_from_single_events(self, test_search, X_fields, Y_field):
		#1: run the splunk search
		search_kwargs = {'timeout':1000, 'exec_mode':'blocking'}
		job = self.jobs.create('search %s | table %s %s' % (test_search, ' '.join(X_fields), Y_field), **search_kwargs)

		#2: iterate through the results
		
		correct = 0
		total = float(job["resultCount"])
		offset = 0
		count = 100
		print "iterating"
		# iterate
		squared_diffs = []
		while (offset < total):
			kwargs_paginate = {'count': count, 'offset':offset}
			search_results = job.results(**kwargs_paginate)
			for result in results.ResultsReader(search_results):
				# result is an EVENT
				if Y_field not in result:
					continue # this probably should be checked; if we accidentally foudn a non-event.
				else:
					prediction  = self.predict_single_event(result, X_fields, Y_field)
					squared_diffs.append((float(result[Y_field]) - prediction)**2)
			offset += count
		
		return .5 * np.average(squared_diffs)


	def calculate_accuracy_from_splunk_prediction_search(self, prediction_search, Y_field):
		#1: cut the fields to just the ones we're interested in
		prediction_search += '| table %s, _test_predict' % Y_field

		#2: run the job
		search_kwargs = {'timeout':1000, 'exec_mode':'blocking'}
		
		job = self.jobs.create(prediction_search, **search_kwargs)

		#3: iterate through the job and count accuracy
		# set up variables
		correct = 0
		total = float(job["resultCount"]) #float for the later accuracy calculation
		offset = 0
		count = 100
		print "iterating"
		squared_diffs = []
		#iterate
		
		while (offset < total):
		
			kwargs_paginate = {'count': count, 'offset':offset}
			search_results = job.results(**kwargs_paginate)
			for result in results.ResultsReader(search_results):
				if Y_field not in result or '_test_predict' not in result:
					print 'skipping'
					continue #this probably should be checked 
				if result[Y_field] == result['_test_predict']:
					correct += 1
				squared_diffs.append((float(result[Y_field]) - float(result['_test_predict'])) **2)
			offset += count
			print offset

		#return accuracy
		return .5 * np.average(squared_diffs)






	def check_accuracy(self, search_string, feature_fields, class_field):
		'''
			check_accuracy(search_string, feature_fields, class_field)

			search_string: string to use in the splunk search to narrow events
			feature_fields: which fields to use to predict
			class_field: field to predict

			returns: accuracy of prediction

			notes: assumes that classifier is already trained. calls predict on each event.
		'''
		# 1: check that classifier is trained:
		if not self.trained:
			raise 'classifier is not trained'


		# 2: predict the search string
		splunk_search = 'search %s | table *' % search_string
		search_kwargs = {'timeout':1000, 'exec_mode':'blocking'} #required fields set to all - check API ("rf=*")
		job = self.jobs.create(splunk_search, **search_kwargs)
		result_count = int(job["resultCount"])

		# 3: iterate and tally accuracy
		correct = 0
		total = 0
		offset = 0
		count = 100
		while (offset < result_count):
			print "offset: %s" % offset
			kwargs_paginate = {'count': count, 'offset':offset}
			search_results = job.results(**kwargs_paginate)
			for result in results.ResultsReader(search_results):
				try:
					if result[class_field] == self.predict(feature_fields, class_field, result):
						correct += 1
						total += 1
					else:
						total += 1
				except:
					continue #tochange
		
			offset += count
			print "curr acc: %f" % (float(correct) / total)

		# 4: calculate percentage
		perc_correct = float(correct)/total
		self.accuracy = perc_correct
		self.accuracy_tested = True

		# 5: return
		return perc_correct



	def evaluate_accuracy(self, search_string, feature_fields, class_field):
		'''
			evaluate_accuracy()

			trains the classifier, then predicts each of the events it trains on and records how many were correct
		'''
		print "Now evaluating %s test set accuracy." % self.__class__.__name__

		#1 : train the classifier
		print "--> Training the classifier..."
		self.train(search_string, feature_fields, class_field)
		print "... done."

		#2 : check accuracy
		print "--> Iterating through test set and checking accuracy..."
		accuracy = self.check_accuracy(search_string, feature_fields, class_field)
		print "done."

		#3 : print result
		print "Accuracy was %f." % accuracy





