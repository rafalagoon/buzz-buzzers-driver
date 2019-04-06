#!/usr/bin/python
#
# Author: fef
# Repository: https://github.com/fefc/buzz-buzzers-driver
# Description: This python code allow you to map Buzz Buzzer USB receiver and their connected Buzzers to keyboard events
# Currently 8 Buzzers are mapped to key events

# This driver is implemented in usserspace and requires the pyusb library
# Some of this code has been inspired by:
# http://rabid-inventor.blogspot.de/2015/06/simulating-keyboard-input-in-python.html

from threading import Thread
from evdev import UInput, InputEvent, ecodes
import usb.core
import usb.util
import signal
import time

USB_VENDOR = 0x054c
USB_PRODUCT = (0x0002, 0x1000)


# The wireless receiver supports 4 individual controllers on 4 separate USB
# interfaces. Each USB interface has two endpoints: one for reading, one
# for writing LED and rumble settings
SLOTS = ((0, 0x81, 0x01), (2, 0x83, 0x03), (4, 0x85, 0x05), (6, 0x87, 0x07))

# Class representing a single wireless receiver. This driver is coded in a
# lazy manner and will bind to the first receiver found on the bus. Support
# for more than one receiver on a single system is an exercise left to the
# reader.

class WirelessReceiver(object):
	def __init__(self, usb_dev):
		self.dev_h = None
		self.usb_device = usb_dev
		if self.usb_device is None:
			raise Exception('wireless receiver not found on USB bus')
		print self.usb_device
		self.claim_interfaces()

	#def find_receiver(self):
	#	usb_device = None
	#	busses = usb.busses()
	#	for bus in busses:
	#		for dev in bus.devices:
	#			if dev.idVendor == USB_VENDOR and (dev.idProduct == USB_PRODUCT[0] or dev.idProduct == USB_PRODUCT[1]):
	#				usb_device = dev
	#				break
	#		if usb_device:
	#			break
	#	return usb_device
	#
	def claim_interfaces(self):
		dev_h = self.usb_device.open()
		config = self.usb_device.configurations[0]
		# setConfiguration can only be called once for the device
		inum = SLOTS[0][0]
		intf = config.interfaces[inum]
		try:
			dev_h.detachKernelDriver(0) #FC
			dev_h.detachKernelDriver(1) #FC
		except Exception, e:
			pass
		dev_h.setConfiguration(config)
		dev_h.claimInterface(intf[0])
		dev_h.setAltInterface(intf[0])
		self.dev_h = dev_h
	#
	def release_interfaces(self):
		self.dev_h.releaseInterface()
		self.dev_h.reset()
	#
	def get_controller_handle(self, number):
		return (self.dev_h, SLOTS[number][1], SLOTS[number][2])
   #
#

# Representation of a Buzz! wireless Buzzer.
# Representation of a single Xbox 360 wireless contoller. Each of the 4
# controllers is tracked and handled separately by the driver code. In order
# to set the LED ring on the controller properly, each controller needs to
# know its controller number (0 through 3).
class Controller(object):
	def __init__(self, controller_handle):
		self.dev_h = controller_handle[0]
		self.inep = controller_handle[1]
		self.outep = controller_handle[2]
		self.driver_fn = None
		self.present = False
	#
	# Method to read a single packet from the controller. Several types of
	# packets may be encountered, but the two interesting ones are presence
	# notification and button/stick updates
	def read_packet(self):
		ctrlBtnArray = [-1] * 4
		try:
			pkt = self.dev_h.interruptRead(self.inep, 8, 1000)

			if (pkt[2] != 0 or pkt[3] != 0 or pkt[4] != 0xF0):
				#First buzzer decompilation
				if bool(pkt[2] & 0b00000001):
					ctrlBtnArray[0] = 0
				if bool(pkt[2] & 0b00010000):
					ctrlBtnArray[0] = 4
				if bool(pkt[2] & 0b00001000):
					ctrlBtnArray[0] = 3
				if bool(pkt[2] & 0b00000100):
					ctrlBtnArray[0] = 2
				if bool(pkt[2] & 0b00000010):
					ctrlBtnArray[0] = 1

				#Second buzzer decompilation
				if bool(pkt[2] & 0b00100000):
					ctrlBtnArray[1] = 5
				if bool(pkt[3] & 0b00000010):
					ctrlBtnArray[1] = 9
				if bool(pkt[3] & 0b00000001):
					ctrlBtnArray[1] = 8
				if bool(pkt[2] & 0b10000000):
					ctrlBtnArray[1] = 7
				if bool(pkt[2] & 0b01000000):
					ctrlBtnArray[1] = 6

				#Third buzzer decompilation
				if bool(pkt[3] & 0b00000100):
					ctrlBtnArray[2] = 10
				if bool(pkt[3] & 0b01000000):
					ctrlBtnArray[2] = 14
				if bool(pkt[3] & 0b00100000):
					ctrlBtnArray[2] = 13
				if bool(pkt[3] & 0b00010000):
					ctrlBtnArray[2] = 12
				if bool(pkt[3] & 0b00001000):
					ctrlBtnArray[2] = 11

				#Fourth buzzer decompilation
				if bool(pkt[3] & 0b10000000):
					ctrlBtnArray[3] = 15
				if bool(pkt[4] & 0b00001000):
					ctrlBtnArray[3] = 19
				if bool(pkt[4] & 0b00000100):
					ctrlBtnArray[3] = 18
				if bool(pkt[4] & 0b00000010):
					ctrlBtnArray[3] = 17
				if bool(pkt[4] & 0b00000001):
					ctrlBtnArray[3] = 16

				#ui.write_event(InputEvent(1, 200, ecodes.EV_KEY, deviceindex[index], 1))

				#self.sleep(200)
				#ui.write(ecodes.EV_KEY, deviceindex[index], 0)


		except Exception, e:
			#interruptRead timedout
			pass
		return ctrlBtnArray
#

# The Buzzers are serviced by a separate thread, so that latency
# is minimized.
# This thread handles the reading from the USB Buzzer stick and
# sends each button to a separate Keyboard simulator thread.
# In total there are 5 threads:
#	-one for reading the USB Buzzer
#	-4 for simulating keyboard presses for each buzzer
class DriverThread(Thread):
	def __init__(self, controller, offset):
		Thread.__init__(self)
		self.threads = [KeyboardSimuThread(0), KeyboardSimuThread(1) , KeyboardSimuThread(2), KeyboardSimuThread(3)]
		self.controller = controller
		self.offset = offset
		self.keep_running = True
	#
	def run(self):
		index2 = 0
		ctrlBtnArray = [-1] * 4
		print "Driver Thread Started!"

		#Start all sub threads that will manage keyboard presses
		self.threads[0].start()
		self.threads[1].start()
		self.threads[2].start()
		self.threads[3].start()

		while self.keep_running:
			#read USB Buzzer
			ctrlBtnArray = self.controller.read_packet()

			#For each buzzer, check is a button has been pressed
			for index in range(len(ctrlBtnArray)):
				#if yes, send the information to the corresponding keyboard thread
				if ctrlBtnArray[index] != -1:
					self.threads[index].simulateKey(deviceindex[ctrlBtnArray[index]+ self.offset])

		self.threads[0].signal()
		self.threads[1].signal()
		self.threads[2].signal()
		self.threads[3].signal()

		print 'Driver Thread terminated!'
	#
	# Each thread runs until explicitly signaled to stop
	def signal(self):
		print "Driver Thread will terminate!"
		self.keep_running = False
	#
#

class KeyboardSimuThread(Thread):
	def __init__(self, thNo):
		Thread.__init__(self)
		self.thNo = thNo
		self.ui = UInput()
		self.keep_running = True
		self.waitingOnKey = True
		self.key = ecodes.KEY_Q
	#
	def run(self):
		print "KeyboardSimuThread Started!"
		while self.keep_running:
			if self.waitingOnKey == False:
				#print "Buzzer " + str(self.thNo)
				#self.ui.write_event(InputEvent(1, 200, ecodes.EV_KEY, self.key, 1)) does not work in Blender
				self.ui.write(ecodes.EV_KEY, self.key, 1) 	#Press key down
				self.ui.syn()
				time.sleep (0.3)							#Hold it down for 300ms so that Blender is able to read it
				self.ui.write(ecodes.EV_KEY, self.key, 0)	#Relase
				self.ui.syn()

				self.waitingOnKey = True					#Now we can send a new key
															#If another key of this buzzer had been pressed it will not be taken in concideration
															# before waitingOnKey is set to True. So 300ms after last key was pressed
			time.sleep (0.1)

		self.ui.close()
		print "KeyboardSimuThread terminated!"

	def simulateKey(self, key):
		#If the thread is waiting for a key we send it, otherwise we ignore it because the thread is already managing one key
		if self.waitingOnKey == True:
			self.key = key
			self.waitingOnKey = False

	# Each thread runs until explicitly signaled to stop
	def signal(self):
		print "KeyboardSimuThread will terminate!"
		self.keep_running = False
	#



# To allow the driver application to be terminated, a signal handler must
# be constructed to receive Ctrl+C and notify each thread to terminate
class SignalHandler(object):
	def __init__(self):
		self.threads = []
	#
	def add_thread(self, th):
		self.threads.append(th)
	#
	def signal(self, signum, frame):
		print "Ctrl+C recieved, I'll tell all threads to terminate!"
		for th in self.threads:
			th.signal()
	#
#


# Actual main application implementation
if __name__ == '__main__':
	if 1:
		deviceindex = [
			#First wirelessReceiver
			ecodes.KEY_A,
			ecodes.KEY_B,
			ecodes.KEY_C,
			ecodes.KEY_D,
			ecodes.KEY_E,


			ecodes.KEY_F, #Inverted for strage reason
			ecodes.KEY_G,
			ecodes.KEY_H,
			ecodes.KEY_I,
			ecodes.KEY_J,

			ecodes.KEY_K,
			ecodes.KEY_L,
			ecodes.KEY_M,
			ecodes.KEY_N,
			ecodes.KEY_O,

			ecodes.KEY_P, #Inverted for strage reason
			ecodes.KEY_Q,
			ecodes.KEY_R,
			ecodes.KEY_S,
			ecodes.KEY_T,

			#second wirelessReceiver
			ecodes.KEY_U,
			ecodes.KEY_V,
			ecodes.KEY_W,
			ecodes.KEY_X,
			ecodes.KEY_Y,

			ecodes.KEY_0,
			ecodes.KEY_1,
			ecodes.KEY_2,
			ecodes.KEY_3,
			ecodes.KEY_4,

			ecodes.KEY_5,
			ecodes.KEY_6,
			ecodes.KEY_7,
			ecodes.KEY_8,
			ecodes.KEY_9,

			ecodes.KEY_COMMA,
			ecodes.KEY_DOT,
			ecodes.KEY_SLASH,
			ecodes.KEY_BACKSLASH,
			ecodes.KEY_MINUS
			]

	wr = []

	usb_device = None
	busses = usb.busses()
	for bus in busses:
		for dev in bus.devices:
			if dev.idVendor == USB_VENDOR and (dev.idProduct == USB_PRODUCT[0] or dev.idProduct == USB_PRODUCT[1]):
				wr.append(WirelessReceiver(dev))

	sh = SignalHandler()
	controllers = []
	threads = []

	#c = Controller()

	for index, wirelessReceiver in enumerate(wr):
		c = Controller(wirelessReceiver.get_controller_handle(0))
		controllers.append(c)
		t = DriverThread(c, index * 20)
		t.start()
		threads.append(t)
		sh.add_thread(t)

	# Set up signal handler
	signal.signal(signal.SIGINT, sh.signal)
	print 'Main driver is running '

	# Spin (busy-wait) so Ctrl+C works properly. Do NOT join on threads in
	# the main loop in Python if you want to be able to catch signals... the
	# signal code will not run until the main thread wakes up, which would
	# not happen in this implementation.
	dead = False
	while not dead:

		# Yield CPU to avoid needless no-ops
		time.sleep(1)

		# Check to see if the threads are still alive
		count = 0
		for t in threads:
			if t.is_alive():
				count += 1
		if count == 0:
			dead = True

	for wirelessReceiver in wr:
		wirelessReceiver.release_interfaces()
	#
	print 'main driver exiting'
	#
#
