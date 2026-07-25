# for artix 7

import sys
import time
import ftd2xx as ftd
import bitstring
import struct
import math

i = 0
#Pass 0 to open() for Channel A and 1 for Channel B
dev = ftd.open(0)

print(dev.getDeviceInfo())
input_file = open(sys.argv[1],"r")
temp_file = open(sys.argv[2],"w")

print_List = []
expectedData_List = []
send_str = bytearray()

read_cmd = 0
write_cmd = 0
#Set device in MPSSE mode
dev.setBitMode(0,0x02)
#initialize JTAG TCK frequency
dev.write(b"\x8B")
dev.write(b"\x86\x3B\x00")	#Reduce clock frequency for MAX 10 due to pin sharing with JTAG

#initialize JTAG pins on Port B
dev.write(b"\x80\x00\x0B")

# 1. Reset and Go to SHIFT-IR
dev.write(b"\x4B\x05\x3F") # Reset
dev.write(b"\x4B\x05\x00") # Reset
dev.write(b"\x4B\x03\x03") # Move to SHIFT-IR

# 2. Shift IDCODE IR (001001) 
# Shift first 5 bits (LSB: 1, 0, 0, 1, 0)
dev.write(b"\x1B\x04\x09") 

# 3. Shift 6th bit (0) and Exit-IR (TMS: 1)
# Using 4B: TDI will stay at the last bit (0) while TMS goes high
dev.write(b"\x4B\x00\x01") 

# 4. Move to SHIFT-DR (TMS: 1, 1, 0, 0)
dev.write(b"\x4B\x03\x03")

# 5. Read 32 bits (4 bytes)
# Command 0x20 is Read Bytes (+ve edge)
dev.write(b"\x20\x03\x00") 
idcode = dev.read(4)
print(f"IDCODE: {idcode.hex()}")

dev.write(b"\x4B\x02\x03")
# 1. Reset and Go to SHIFT-IR
dev.write(b"\x4B\x03\x03") # Move to SHIFT-IR

# 2. Shift first 5 bits of USER1 (00010)
dev.write(b"\x1B\x04\x02") 

dev.write(b"\x4B\x00\x01")
dev.write(b"\x4B\x01\x01")


# Start testing(Only SHIFTDR, EXITDR1, and CAPTUREDR states are needed)
#Enter input vector
#Read output vector
exit = 0
iter_no = 0
while exit != 1:
	k = 0
	send_str = bytearray()
	while write_cmd < 61440:
		fileData = input_file.readline()
		if len(fileData)==0 :
			break;
		print_List.append([])
		lineContent	= fileData.split(' ')
		inputData = lineContent[0]
		maskbits = lineContent[2]
		expectedData = lineContent[1]
		expectedData_List.append(expectedData)

		inputLen = len(inputData)
		# temp_file.write(inputData+' ')
		print_List[k].append((inputData+' '))
		outputLen = len(expectedData)
		
		# # If first bit is needed while shifting to SHIFTDR state then uncomment
		# first_bit_data = (int(inputData[-1],2) << 7) | 0x01
		# sendByteArray =bytearray([0x4B,0x02,first_bit_data])
		# send_str.extend(sendByteArray)
		# write_cmd += 3
		
		# If no first bit is needed then
		send_str.extend(b"\x4B\x02\x01")		#IDLE to Shift DR state with TMS with TDI = '0'
		write_cmd += 3
		if inputLen <= 9 and inputLen > 1:
			#Pass all bits in s_shift state (Case 1)
			#Pass all but last last bit in s_shift state (Case 2)
			inputTemp = int(inputData[1:inputLen],2)
			lastBit = int(inputData[0],2)
			tempLen = inputLen-2
			sendByteArray = bytearray([0x1B,tempLen,inputTemp])
			send_str.extend(sendByteArray)
			write_cmd += 3
		elif inputLen == 1:
			lastBit = int(inputData[0],2)
		else:
			tempLen = inputLen
			no_of_bytes = (tempLen & (~7)) >> 3
			no_of_bits = tempLen & 7
			if no_of_bits == 0:
				no_of_bits += 8
				no_of_bytes -= 1
			bytesminusOne = no_of_bytes - 1
			bytesL = bytesminusOne & 0xFF
			bytesH = bytesminusOne >> 8
			byte_array = ""
			i = 0
			j = inputLen
			# Append bytes send command
			byteList = [0x19,bytesL,bytesH]
			write_cmd += 3
			while i < no_of_bytes:
				temp_byte_array = inputData[j-8:j]
				# print(temp_byte_array)
				# byte_array = byte_array + int(temp_byte_array,2)
				j -= 8
				i += 1
				byteList.append(int(temp_byte_array,2))
				write_cmd += 1
			sendByteArray = bytearray(byteList)
			send_str.extend(sendByteArray)	
			
			if no_of_bits == 1:
				lastBit = int(inputData[0],2)
			else:
				tempLen = no_of_bits-2
				# print(inputData[1:no_of_bits])
				inputTemp = int(inputData[1:no_of_bits],2)
				lastBit = int(inputData[0],2)
				sendByteArray = bytearray([0x1B,tempLen,inputTemp])
				send_str.extend(sendByteArray)
				write_cmd += 3
			
		#Shift last bit(MSB) in DR and go to IDLE state through
		# print(lastBit)
		sendByteArray = bytearray([0x4B,0x02,((lastBit & 0x1)<< 7)| 0x03])
		# sendByteArray = bytearray([0x4B,0x02,0x03])
		send_str.extend(sendByteArray)		
		write_cmd += 3
		
		send_str.extend(b"\x4B\x02\x01")
		write_cmd += 3
		
		if outputLen <= 9 and outputLen > 1:	
			outbitLen = (outputLen-2)
			# sendByteArray = [0x3E,outbitLen,0]
			sendByteArray = [0x2E,outbitLen]
			lastBit = 0
			send_str.extend(sendByteArray)
			# write_cmd += 3
			write_cmd += 2
			read_cmd += 1
		elif outputLen == 1:
			lastBit = 0
		else:
			tempLen = outputLen
			no_of_bytes = (tempLen & (~7)) >> 3
			no_of_bits = tempLen & 7
			if no_of_bits == 0:
				no_of_bits += 8
				no_of_bytes -= 1
			bytesminusOne = no_of_bytes - 1
			bytesL = bytesminusOne & 0xFF
			bytesH = bytesminusOne >> 8
			byte_array = ""
			i = 0
			# Append bytes send command
			byteList = [0x2C,bytesL,bytesH]
			write_cmd += 3
			while i < no_of_bytes:
				i += 1
				# byteList.append(0)
				# write_cmd += 1
				read_cmd += 1
			sendByteArray = bytearray(byteList)
			send_str.extend(sendByteArray)	
			
			if no_of_bits == 1:
				lastBit = 0
			else:
				tempLen = no_of_bits-2
				lastBit = 0
				# sendByteArray = bytearray([0x3E,tempLen,0])
				sendByteArray = bytearray([0x2E,tempLen])
				send_str.extend(sendByteArray)
				# write_cmd += 3
				write_cmd += 2
				read_cmd +=1 
			
		sendByteArray = bytearray([0x6B,0x02,((lastBit & 0x1)<< 7)| 0x03])
		# sendByteArray = bytearray([0x6B,0x02,0x03])
		send_str.extend(sendByteArray)		
		read_cmd += 1
		write_cmd += 3
		k += 1

	byte_send = bytes(send_str)
	ret_val = dev.write(byte_send)
	usb_read_data = dev.read(read_cmd)
	j = 0
	k = 0
	l = 0
	read_bytes_str = ""
	usb_read_len = len(usb_read_data)
	while j < usb_read_len:
		if(outputLen <= 9 and outputLen > 1):
			# read_data = (struct.unpack('>B',usb_read_data[j:j+1]))[0] 
			# firstBitStr = format(read_data,'08b')
			# print(firstBitStr)
			# j += 1
			read_data = (struct.unpack('>B',usb_read_data[j:j+1]))[0] 
			read_str = format(read_data,'08b')[:outputLen-1]
			j += 1
			#print(read_str)
			read_data = (struct.unpack('>B',usb_read_data[j:j+1]))[0] 
			lastBitStr = format(read_data,'08b')[2]
			read_str = lastBitStr + read_str
			j += 1
			# print(lastBitStr)
		elif outputLen == 1:
			read_data = (struct.unpack('>B',usb_read_data[j:j+1]))[0] 
			lastBitStr = format(read_data,'08b')[2]
			read_str = lastBitStr
			j += 1
		else:
			l = 0
			read_bytes_str = ""
			while l < no_of_bytes:
				read_bytes_str = "{0:08b}".format(int(usb_read_data[j:j+1].hex(),16)) + read_bytes_str
				l += 1
				j += 1
			if(no_of_bits > 1):	
				read_bits_data = (struct.unpack('>B',usb_read_data[j:j+1]))[0] 
				read_bits_str = format(read_bits_data,'08b')
				read_str = read_bits_str[:no_of_bits-1] + read_bytes_str
				j += 1
				read_data = (struct.unpack('>B',usb_read_data[j:j+1]))[0] 
				lastBitStr = format(read_data,'08b')[2]
				read_str = lastBitStr + read_str
				j += 1
			else:
				read_str = read_bytes_str
				read_data = (struct.unpack('>B',usb_read_data[j:j+1]))[0] 
				lastBitStr = format(read_data,'08b')[2]
				read_str = lastBitStr + read_str
				j += 1
		# temp_file.write(read_str)
		
		print_List[k].append(read_str)
		if(read_str == expectedData_List[k]):
			print_List[k].append(" Success\n")
		else:
			print_List[k].append(" Failure\n")
		k += 1
		
	l = 0
	for i in print_List:
		for l in i:
			temp_file.write(l)	
	if(write_cmd >= 61440):
		read_cmd = 0
		write_cmd = 0
		exit = 0
		print_List = []
		expectedData_List = []
		iter_no += 1
	else:
		exit = 1

#Close files
input_file.close()
temp_file.close()
#Reset device
dev.setBitMode(0,0)