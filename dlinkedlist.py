#!/usr/bin/env python

#
#############################################################################
#
# dlinkedlist.py - Doubly-Linked List class
# Copyright (C) 2015, testcams.com
#
# This module is licensed under GPL v3: http://www.gnu.org/licenses/gpl-3.0.html
#
#############################################################################
#


class LinkedList():
	def __init__(self):
		self._head = None
		self._tail = None
		self._countObjs = 0
	def insert(self, objIns):
		#
		# keeps the list sorted by key; objects with equal keys stay in insertion order. the
		# scan starts at the tail because objects normally arrive roughly oldest-to-newest
		# (and realtime captures are always newest), which makes the common case O(1) instead
		# of walking the whole list for every insert
		#
		objInList = self._tail
		while objInList and objIns._key < objInList._key:
			objInList = objInList._prev
		if objInList is None:
			# smallest key - insert at head
			objIns._prev = None
			objIns._next = self._head
			if self._head:
				self._head._prev = objIns
			else:
				self._tail = objIns
			self._head = objIns
		else:
			# insert after objInList
			objIns._prev = objInList
			objIns._next = objInList._next
			if objInList._next:
				objInList._next._prev = objIns
			else:
				self._tail = objIns
			objInList._next = objIns
		self._countObjs += 1
	def remove(self, objRem):
		if objRem._prev:
			objRem._prev._next = objRem._next
		else:
			self._head = objRem._next
		if objRem._next:
			objRem._next._prev = objRem._prev
		else:
			self._tail = objRem._prev
		objRem._prev = objRem._next = None
		self._countObjs -= 1
	def head(self):
		return self._head
	def tail(self):
		return self._tail
	def count(self):
		return self._countObjs
	def dump(self):
		obj = self.head()
		i = 0
		while obj:
			print("{:d}, {}: key={}".format(i, obj, obj._key))
			obj = obj.llNext()
			i += 1

class LinkedListObj():
	def __init__(self, key, linkedList=None):
		self._key = key
		self._prev = None
		self._next = None
		if linkedList:
			linkedList.insert(self)
		# else obj user will call insert() himself
	# note I named these llNext()/llPrev() instead of  next()/prev() in case inherited class wants to claim those generic method names for itself
	def llNext(self):
		return self._next
	def llPrev(self):
		return self._prev
